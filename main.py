import os
import streamlit as st
import requests
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import plotly.express as px
from wordcloud import WordCloud
from openai import OpenAI

st.set_page_config(page_title="영화 관객 반응 AI 분석", layout="wide")
st.title("🎬 어제 1위 영화, 관객 반응은?")
st.caption("박스오피스 → 유튜브 예고편 댓글 → 그래프 · 워드클라우드 · AI 분석")

KOBIS_KEY = st.secrets["KOBIS_KEY"]
YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
client = OpenAI(api_key=st.secrets["SOLAR_API_KEY"], base_url="https://api.upstage.ai/v1")

# 한글 폰트 준비 (없으면 한 번만 내려받기)
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
FONT_PATH = "NanumGothic.ttf"
if not os.path.exists(FONT_PATH):
    try:
        with open(FONT_PATH, "wb") as f:
            f.write(requests.get(FONT_URL).content)
    except Exception:
        st.error("한글 폰트를 내려받지 못했어요.")

yesterday = (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=1)).strftime("%Y%m%d")

# 1. 어제 1위 영화
kobis_url = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
data = requests.get(kobis_url, params={"key": KOBIS_KEY, "targetDt": yesterday}, timeout=10).json()

if "faultInfo" in data:
    st.error("영화 데이터를 불러오지 못했습니다.")
    st.stop()

top = data["boxOfficeResult"]["dailyBoxOfficeList"][0]
movie_name = top["movieNm"]

c1, c2, c3 = st.columns(3)
c1.metric("어제 1위", movie_name)
c2.metric("관객수", f"{int(top['audiCnt']):,}명")
c3.metric("누적 관객", f"{int(top['audiAcc']):,}명")
st.divider()

# 2. 유튜브 예고편 찾기
st.subheader(f"🔍 '{movie_name}' 예고편")
search = requests.get("https://www.googleapis.com/youtube/v3/search", params={
    "key": YOUTUBE_KEY, "q": f"{movie_name} 예고편",
    "part": "snippet", "type": "video", "maxResults": 1,
}, timeout=10).json()

if not search.get("items"):
    st.warning("예고편을 찾지 못했습니다.")
    st.stop()

video_id = search["items"][0]["id"]["videoId"]
st.video(f"https://www.youtube.com/watch?v={video_id}")

# 3. 댓글 가져오기 (좋아요 많은 순)
cres = requests.get("https://www.googleapis.com/youtube/v3/commentThreads", params={
    "key": YOUTUBE_KEY, "videoId": video_id,
    "part": "snippet", "maxResults": 100, "order": "relevance",
}, timeout=10)

if cres.status_code != 200:
    st.warning(f"댓글을 가져오지 못했습니다. (상태코드: {cres.status_code})")
    st.stop()

rows = []
for it in cres.json().get("items", []):
    snip = it["snippet"]["topLevelComment"]["snippet"]
    rows.append((snip["textOriginal"], snip.get("likeCount", 0)))
rows.sort(key=lambda r: r[1], reverse=True)

comments = [t for t, _ in rows]
likes = [n for _, n in rows]

if len(comments) == 0:
    st.warning("댓글이 없거나 막혀 있습니다.")
    st.stop()

st.metric("가져온 댓글 수", f"{len(comments)}개")
joined = "\n".join(comments)

# 4. 단어 빈도 그래프
words = " ".join(comments).split()
words = [w for w in words if len(w) > 1]
top20 = Counter(words).most_common(20)

st.subheader("📊 자주 나온 단어 TOP 20")
freq = {"단어": [w for w, _ in top20], "횟수": [n for _, n in top20]}
fig = px.bar(freq, x="횟수", y="단어", orientation="h")
fig.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig, use_container_width=True)

# 5. 워드클라우드
st.subheader("☁️ 댓글 워드클라우드")
wc = WordCloud(font_path=FONT_PATH, width=800, height=400,
               background_color="white").generate(" ".join(words))
st.image(wc.to_array())
st.divider()


def ask_ai(system, user):
    resp = client.chat.completions.create(
        model="solar-open2",
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        reasoning_effort="none",
    )
    return resp.choices[0].message.content


# 6. AI 세 줄 요약
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

# 7. 한국어 번역
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

# 8. 댓글 기반 질문답변
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

st.divider()

# 9. AI 채팅창
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

with st.expander("실제 댓글 보기 (좋아요 많은 순)"):
    st.dataframe({"좋아요": likes, "댓글": comments}, use_container_width=True)
