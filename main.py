import os
import json
import streamlit as st
import requests
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.express as px
from wordcloud import WordCloud
from openai import OpenAI

st.set_page_config(page_title="영화 기대지수 랭킹", layout="wide")
st.title("🎬 어제의 극장가 리포트")
st.caption("박스오피스 → 유튜브 예고편 댓글 → AI 기대지수 랭킹")

KOBIS_KEY = st.secrets["KOBIS_KEY"]
YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
client = OpenAI(api_key=st.secrets["SOLAR_API_KEY"], base_url="https://api.upstage.ai/v1")

# 한글 폰트 준비 (없으면 한 번만 내려받기)
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
FONT_PATH = "NanumGothic.ttf"
if not os.path.exists(FONT_PATH):
    try:
        with open(FONT_PATH, "wb") as f:
            f.write(requests.get(FONT_URL, timeout=30).content)
    except Exception:
        st.error("한글 폰트를 내려받지 못했어요.")

yesterday = (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=1)).strftime("%Y%m%d")


def ask_ai(system, user):
    """Solar AI에게 물어보고 답을 돌려준다."""
    resp = client.chat.completions.create(
        model="solar-open2",
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        reasoning_effort="none",
    )
    return resp.choices[0].message.content


@st.cache_data(ttl=3600)
def get_comments(movie_name):
    """영화 이름으로 예고편을 찾아 댓글을 가져온다. (1시간 동안 기억)"""
    search = requests.get("https://www.googleapis.com/youtube/v3/search", params={
        "key": YOUTUBE_KEY, "q": f"{movie_name} 예고편",
        "part": "snippet", "type": "video", "maxResults": 1,
    }, timeout=30).json()

    if not search.get("items"):
        return None, []

    vid = search["items"][0]["id"]["videoId"]
    cres = requests.get("https://www.googleapis.com/youtube/v3/commentThreads", params={
        "key": YOUTUBE_KEY, "videoId": vid,
        "part": "snippet", "maxResults": 100, "order": "relevance",
    }, timeout=30)

    if cres.status_code != 200:
        return vid, []

    rows = []
    for it in cres.json().get("items", []):
        snip = it["snippet"]["topLevelComment"]["snippet"]
        rows.append((snip["textOriginal"], snip.get("likeCount", 0)))
    rows.sort(key=lambda r: r[1], reverse=True)
    return vid, rows


# ── 1. 박스오피스 불러오기 ────────────────────────────
kobis_url = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
try:
    data = requests.get(kobis_url, params={"key": KOBIS_KEY, "targetDt": yesterday}, timeout=30).json()
except Exception:
    st.error("영화진흥위원회 서버가 응답하지 않습니다. 잠시 후 새로고침해 주세요.")
    st.stop()

if "faultInfo" in data:
    st.error("영화 데이터를 불러오지 못했습니다.")
    st.stop()

movies = data["boxOfficeResult"]["dailyBoxOfficeList"]
st.caption(f"기준일: {yesterday}")

df = pd.DataFrame(movies)
for col in ["rank", "audiCnt", "audiAcc", "scrnCnt"]:
    df[col] = pd.to_numeric(df[col])
df = df.sort_values("rank")

top1 = df.iloc[0]
c1, c2, c3 = st.columns(3)
c1.metric("어제 1위", top1["movieNm"])
c2.metric("관객수", f"{int(top1['audiCnt']):,}명")
c3.metric("누적 관객", f"{int(top1['audiAcc']):,}명")

st.subheader("📋 박스오피스 TOP 10")
st.dataframe(
    df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].rename(columns={
        "rank": "순위", "movieNm": "영화명", "openDt": "개봉일",
        "audiCnt": "관객수", "audiAcc": "누적관객", "scrnCnt": "스크린수"}),
    hide_index=True, use_container_width=True)

st.divider()

# ── 2. ⭐ TOP 5 기대지수 랭킹 ─────────────────────────
st.subheader("🏆 AI 기대지수 랭킹 (TOP 5)")
st.write("1~5위 영화의 예고편 댓글을 AI가 읽고, 관객 반응이 좋은 순으로 다시 줄을 세웁니다.")

if st.button("기대지수 계산하기 🏆"):
    top5 = df.head(5)
    results = []
    bar = st.progress(0.0, text="시작합니다...")

    for i, (_, row) in enumerate(top5.iterrows()):
        name = row["movieNm"]
        bar.progress((i + 0.5) / 5, text=f"'{name}' 댓글을 읽는 중...")
        try:
            _, rows = get_comments(name)
            texts = [t for t, _ in rows][:60]
            if len(texts) == 0:
                results.append({"영화명": name, "기대지수": None, "한줄평": "댓글을 찾지 못했습니다"})
                continue

            answer = ask_ai(
                "너는 영화 관객 반응 분석가야. 아래 유튜브 예고편 댓글을 읽고 "
                "관객의 기대·호감 정도를 0~100 사이 정수 점수로 매겨. "
                '반드시 아래 JSON 형식으로만 답해. 다른 말은 절대 붙이지 마.\n'
                '{"score": 정수, "comment": "한국어 한 줄 평"}',
                "\n".join(texts))

            start, end = answer.find("{"), answer.rfind("}")
            parsed = json.loads(answer[start:end + 1])
            results.append({
                "영화명": name,
                "기대지수": int(parsed["score"]),
                "한줄평": parsed["comment"],
            })
        except Exception:
            results.append({"영화명": name, "기대지수": None, "한줄평": "분석에 실패했습니다"})

        bar.progress((i + 1) / 5, text=f"'{name}' 완료")

    bar.empty()

    rank_df = pd.DataFrame(results).dropna(subset=["기대지수"])
    if len(rank_df) == 0:
        st.error("기대지수를 계산하지 못했어요 😢 잠시 후 다시 시도해 주세요.")
    else:
        rank_df = rank_df.sort_values("기대지수", ascending=False).reset_index(drop=True)
        rank_df.insert(0, "AI순위", range(1, len(rank_df) + 1))

        best = rank_df.iloc[0]
        st.success(f"🥇 **{best['영화명']}** — 기대지수 {int(best['기대지수'])}점\n\n{best['한줄평']}")

        st.dataframe(rank_df, hide_index=True, use_container_width=True)

        fig = px.bar(rank_df, x="기대지수", y="영화명", orientation="h",
                     range_x=[0, 100], text="기대지수")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)

        st.caption("💡 관객수 순위와 기대지수 순위가 다르면, 흥행은 덜해도 반응은 좋은 영화입니다.")

st.divider()

# ── 3. 영화 하나 골라서 자세히 보기 ───────────────────
st.subheader("🔍 영화 하나 자세히 보기")
picked = st.selectbox("영화를 고르세요", df["movieNm"].tolist())

vid, rows = get_comments(picked)
if vid is None:
    st.warning("예고편을 찾지 못했습니다.")
    st.stop()

st.video(f"https://www.youtube.com/watch?v={vid}")

comments = [t for t, _ in rows]
likes = [n for _, n in rows]

if len(comments) == 0:
    st.warning("댓글이 없거나 막혀 있습니다.")
    st.stop()

st.metric("가져온 댓글 수", f"{len(comments)}개")
joined = "\n".join(comments)

# 단어 빈도 그래프
words = [w for w in " ".join(comments).split() if len(w) > 1]
top20 = Counter(words).most_common(20)

st.subheader("📊 자주 나온 단어 TOP 20")
freq = {"단어": [w for w, _ in top20], "횟수": [n for _, n in top20]}
fig = px.bar(freq, x="횟수", y="단어", orientation="h")
fig.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig, use_container_width=True)

# 워드클라우드
st.subheader("☁️ 댓글 워드클라우드")
try:
    wc = WordCloud(font_path=FONT_PATH, width=800, height=400,
                   background_color="white").generate(" ".join(words))
    st.image(wc.to_array())
except Exception:
    st.warning("워드클라우드를 만들지 못했어요.")

# AI 세 줄 요약
st.subheader("🤖 AI 세 줄 요약")
if st.button("세 줄로 요약하기"):
    with st.spinner("AI가 댓글을 읽고 있어요..."):
        try:
            st.info(ask_ai(
                "너는 댓글 분석가야. 받은 댓글 전체의 전반적인 반응을 한국어 세 줄로 요약하고, "
                "마지막 줄에 긍정과 부정의 대략적인 비율(백분율)을 덧붙여. 반드시 순수 한국어로만 답해.",
                joined))
        except Exception:
            st.error("요약을 받지 못했어요 😢")

# 한국어 번역
st.subheader("🌏 AI 한국어 번역")
if st.button("댓글 번역하기"):
    with st.spinner("AI가 번역하고 있어요..."):
        try:
            st.info(ask_ai(
                "너는 번역가야. 받은 댓글들을 한 줄에 하나씩 한국어로 번역해. "
                "이미 한국어인 댓글은 그대로 둬. 반드시 순수 한국어로만 답해.",
                "\n".join(comments[:30])))
        except Exception:
            st.error("번역에 실패했어요 😢")

# 댓글 기반 질문답변
st.subheader("💬 댓글에 대해 물어보기")
question = st.text_input("예) 사람들이 가장 아쉬워하는 점은?")
if question:
    with st.spinner("AI가 댓글을 뒤지고 있어요..."):
        try:
            st.info(ask_ai(
                "너는 댓글 분석가야. 아래 댓글들만 근거로 삼아 질문에 답해. "
                "댓글에 없는 내용은 지어내지 마. 반드시 순수 한국어로만 답해.",
                f"[질문]\n{question}\n\n[댓글]\n{joined}"))
        except Exception:
            st.error("답변을 받지 못했어요 😢")

with st.expander("실제 댓글 보기 (좋아요 많은 순)"):
    st.dataframe({"좋아요": likes, "댓글": comments}, use_container_width=True)

st.divider()

# ── 4. AI 채팅창 ──────────────────────────────────────
st.subheader("🧑‍🏫 AI 데이터 분석 선생님과 대화하기")

SYSTEM_PROMPT = "너는 따뜻하고 친절한 데이터 분석 선생님이야. 반드시 순수 한국어로만 답해"

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

user_input = st.chat_input("궁금한 것을 물어보세요!")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        try:
            stream = client.chat.completions.create(
                model="solar-open2",
                messages=st.session_state.messages,
                reasoning_effort="none",
                stream=True,
            )
            answer = st.write_stream(
                chunk.choices[0].delta.content or ""
                for chunk in stream if chunk.choices
            )
            st.session_state.messages.append({"role": "assistant", "content": answer})
        except Exception:
            st.error("응답을 받지 못했어요 😢")
