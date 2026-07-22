import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

st.set_page_config(page_title="어제의 박스오피스", layout="wide")
st.title("🎬 어제의 박스오피스")

# 인증키는 코드에 쓰지 않고 비밀 금고에서 꺼내옵니다
KOBIS_KEY = st.secrets["KOBIS_KEY"]

# '어제' 날짜를 한국 시간 기준으로 자동 계산
yesterday = (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=1)).strftime("%Y%m%d")
st.caption(f"기준일: {yesterday}")

url = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

try:
    response = requests.get(url, params={"key": KOBIS_KEY, "targetDt": yesterday}, timeout=10)
    data = response.json()
except Exception:
    st.error("영화진흥위원회 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    st.stop()

if "faultInfo" in data:
    st.error("요청이 거절되었습니다. 비밀 금고의 KOBIS_KEY가 올바른지 확인해 주세요.")
    st.stop()

movies = data["boxOfficeResult"]["dailyBoxOfficeList"]
df = pd.DataFrame(movies)

# 숫자가 문자열로 오기 때문에 진짜 숫자로 바꿔줍니다
for col in ["rank", "audiCnt", "audiAcc", "scrnCnt"]:
    df[col] = pd.to_numeric(df[col])

df = df.sort_values("rank")

top = df.iloc[0]
col1, col2, col3 = st.columns(3)
col1.metric("어제 1위", top["movieNm"])
col2.metric("어제 관객수", f"{top['audiCnt']:,}명")
col3.metric("누적 관객", f"{top['audiAcc']:,}명")

st.subheader("📋 박스오피스 TOP 10")
table = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].rename(columns={
    "rank": "순위",
    "movieNm": "영화명",
    "openDt": "개봉일",
    "audiCnt": "관객수",
    "audiAcc": "누적관객",
    "scrnCnt": "스크린수",
})
st.dataframe(table, hide_index=True, use_container_width=True)

st.subheader("📊 관객수 TOP 5")
top5 = df.head(5)
st.bar_chart(top5.set_index("movieNm")["audiCnt"])
