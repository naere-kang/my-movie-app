import streamlit as st
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from openai import OpenAI

st.set_page_config(page_title="영화 관객 반응 분석", layout="wide")
st.title("🎬 어제 1위 영화, 관객 반응은?")
st.caption("박스오피스 → 유튜브 예고편 댓글 → AI 요약")

KOBIS_KEY = st.secrets["KOBIS_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]
SOLAR_API_KEY = st.secrets["SOLAR_API_KEY"]

yesterday = (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=1)).strftime("%Y%m%d")

# 1단계. 어제 1위 영화 알아내기
kobis_url = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
res = requests.get(kobis_url, params={"key": KOBIS_KEY, "targetDt": yesterday}, timeout=10)
data = res.json()

if "faultInfo" in data:
    st.error("영화 데이터를 불러오지 못했습니다. KOBIS_KEY를 확인해 주세요.")
    st.stop()

top = data["boxOfficeResult"]["dailyBoxOfficeList"][0]
movie_name = top["movieNm"]

col1, col2, col3 = st.columns(3)
col1.metric("어제 1위", movie_name)
col2.metric("관객수", f"{int(top['audiCnt']):,}명")
col3.metric("누적 관객", f"{int(top['audiAcc']):,}명")

st.divider()

# 2단계. 유튜브에서 예고편 찾기
st.subheader(f"🔍 '{movie_name}' 예고편")

search = requests.get("https://www.googleapis.com/youtube/v3/search", params={
    "key": YOUTUBE_API_KEY,
    "q": f"{movie_name} 예고편",
    "part": "snippet",
    "type": "video",
    "maxResults": 1,
}, timeout=10).json()

if not search.get("items"):
    st.warning("유튜브에서 예고편을 찾지 못했습니다.")
    st.stop()

video_id = search["items"][0]["id"]["videoId"]
st.video(f"https://www.youtube.com/watch?v={video_id}")

# 3단계. 댓글 가져오기
cres = requests.get("https://www.googleapis.com/youtube/v3/commentThreads", params={
    "key": YOUTUBE_API_KEY,
    "videoId": video_id,
    "part": "snippet",
    "maxResults": 50,
    "order": "relevance",
}, timeout=10)

if cres.status_code != 200:
    st.warning(f"댓글을 가져오지 못했습니다. (상태코드: {cres.status_code})")
    st.stop()

comments = [
    it["snippet"]["topLevelComment"]["snippet"]["textOriginal"]
    for it in cres.json().get("items", [])
]

if len(comments) == 0:
    st.warning("이 영상은 댓글이 없거나 막혀 있습니다.")
    st.stop()

st.caption(f"댓글 {len(comments)}개를 읽었습니다.")

# 4단계. AI에게 세 줄 요약 부탁하기
st.subheader("🤖 AI가 읽은 관객 반응")

client = OpenAI(api_key=SOLAR_API_KEY, base_url="https://api.upstage.ai/v1")

prompt = f"""아래는 영화 '{movie_name}' 예고편 유튜브 댓글입니다.
관객들의 반응을 한국어 세 줄로 요약해 주세요.
좋은 반응과 아쉬운 반응을 균형 있게 담아주세요.

{chr(10).join(comments)}"""

try:
    with st.spinner("AI가 댓글을 읽는 중..."):
        answer = client.chat.completions.create(
            model="solar-pro2",
            messages=[{"role": "user", "content": prompt}],
        )
    st.success(answer.choices[0].message.content)
except Exception as e:
    st.error(f"AI 요약에 실패했습니다.\n\n{e}")

with st.expander("실제 댓글 보기"):
    for c in comments[:20]:
        st.write("•", c)
