# app.py
import os, sys, subprocess

import streamlit as st
import pandas as pd

from crawler import (
    crawl_kakao_reviews,
    crawl_google_reviews,
    crawl_naver_reviews,
)
from analysis import (
    analyze_reviews,
    generate_prompt,
    generate_consumer_prompt,
)

# 페이지 설정
st.set_page_config(page_title="리뷰 분석 앱", layout="wide")
st.title("🍽️ 식당 리뷰 크롤링 & 분석")

# 1) 세션 스테이트 초기화
if 'submitted' not in st.session_state:
    st.session_state.submitted = False

def on_submit():
    st.session_state.submitted = True

# 2) 사이드바 폼
with st.sidebar:
    with st.form('control_form'):
        restaurant_name = st.text_input("식당 이름을 입력하세요")
        user_type       = st.radio("모드 선택", ("식당주인용", "고객용"))
        st.form_submit_button("🔍 분석 시작", on_click=on_submit)

# 3) 분석 전 대기
if not st.session_state.submitted:
    st.info("사이드바에서 식당 이름을 입력하고 ‘분석 시작’ 버튼을 눌러 주세요.")
    st.stop()

# 4) 입력 검증
if not restaurant_name:
    st.warning("식당 이름을 입력해야 합니다.")
    st.stop()

# 5) 크롤링 (한 번만 실행, 캐시)
@st.cache_data(show_spinner=False)
def get_all_reviews(name: str):
    kakao  = crawl_kakao_reviews(name)
    google = crawl_google_reviews(name)
    naver  = crawl_naver_reviews(name)
    return kakao + google + naver

with st.spinner("1/3 크롤링 중…"):
    all_reviews = get_all_reviews(restaurant_name)

if not all_reviews:
    st.error("리뷰를 찾지 못했습니다.")
    st.stop()

# 6) 원본 리뷰 테이블
df = pd.DataFrame(all_reviews)
st.subheader("✅ 수집된 원본 리뷰")
st.dataframe(df[["platform","reviewer","text","rating","date"]], height=300)

# 7) 감성·키워드 분석
with st.spinner("2/3 감성 분석 및 키워드 추출…"):
    df_proc, keywords, pos_ratio, neg_ratio, top_pos, top_neg, aspects, total = analyze_reviews(df)

# 8) 프롬프트 생성 (한 번만)
if 'prompt' not in st.session_state:
    if user_type == "식당주인용":
        df_kw = pd.DataFrame({
            aspect: [", ".join(f"{w}({s:.2f})" for w, s in kws)]
            for aspect, kws in keywords.items()
        }, index=["키워드"]).T
        st.subheader("🔑 핵심 키워드 (테이블)")
        st.table(df_kw)
        st.write(f"긍정 비율: {pos_ratio:.1f}%  |  부정 비율: {neg_ratio:.1f}%")

        with st.spinner("3/3 주인용 LLM 프롬프트 생성…"):
            prompt = generate_prompt(
                name=restaurant_name,
                keywords=keywords,
                pos_ratio=pos_ratio,
                neg_ratio=neg_ratio,
                aspects=aspects,
                top_pos=top_pos,
                top_neg=top_neg,
                classified_count=total
            )
    else:
        with st.spinner("3/3 고객용 LLM 프롬프트 생성…"):
            prompt = generate_consumer_prompt(
                name=restaurant_name,
                keywords=keywords,
                pos_ratio=pos_ratio,
                neg_ratio=neg_ratio,
                aspects=aspects,
                top_pos=top_pos,
                top_neg=top_neg,
                classified_count=total
            )
    st.session_state['prompt'] = prompt

prompt = st.session_state['prompt']

# 9) 프롬프트 출력
st.subheader("📝 LLM 요청 프롬프트")
st.code(prompt, language="plain")

# 10) Gemini 전송 버튼
if st.button("🔗 Gemini에 전송"):
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    send_script = os.path.join(script_dir, "send_prompt.py")
    # 백그라운드로 실행
    subprocess.Popen([sys.executable, send_script, prompt])
    st.success("Gemini 전송 스크립트를 실행했습니다. 브라우저 창을 확인해주세요.")
