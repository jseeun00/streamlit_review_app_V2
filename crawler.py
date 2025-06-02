import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# --- 크롤링 함수들 정의 시작 ---
MAX_REVIEWS = 100
CLICK_BATCH = 10

def init_driver():
    # ① 최소 옵션(Headless, No-Sandbox, Dev-Shm-Usage)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    # ② chromedriver 경로 결정: ENV → which() → (없으면 에러)
    env_drv = os.getenv("CHROMEDRIVER_BIN")
    if env_drv and Path(env_drv).is_file():
        driver_path = env_drv
    elif (drv := shutil.which("chromedriver")):
        driver_path = drv
    else:
        raise FileNotFoundError(
            "chromedriver를 찾을 수 없습니다. "
            "컨테이너에 chromium-driver 패키지가 설치되어 있는지 확인하세요."
        )
    service = Service(driver_path)

    # ③ chromium 바이너리 경로 결정: ENV → which() → (없으면 에러)
    env_chrome = os.getenv("CHROME_BIN")
    if env_chrome and Path(env_chrome).is_file():
        chrome_path = env_chrome
    elif (bin1 := shutil.which("chromium")):
        chrome_path = bin1
    elif (bin2 := shutil.which("chromium-browser")):
        chrome_path = bin2
    else:
        raise FileNotFoundError(
            "Chrome/Chromium 바이너리를 찾을 수 없습니다. "
            "컨테이너에 chromium 패키지가 설치되어 있는지 확인하세요."
        )
    options.binary_location = chrome_path  # 여기가 반드시 필요합니다!

    # ④ 최종 드라이버 객체 반환
    return webdriver.Chrome(service=service, options=options)


# --- Kakao Map Functions ---
def crawl_kakao_reviews(restaurant_name):
    import re
    driver = init_driver(headless=False)
    print(f"[Kakao] '{restaurant_name}' 검색 시작")
    try:
        driver.get("https://map.kakao.com/")
        wait = WebDriverWait(driver, 10)

        # 검색어 입력
        box = wait.until(EC.presence_of_element_located((By.ID, "search.keyword.query")))
        box.send_keys(restaurant_name, Keys.RETURN)
        print("[Kakao] 검색어 전송 완료")
        time.sleep(2)

        # dimmedLayer 제거 후 '더보기' 클릭 시도
        try:
            dimmed = driver.find_element(By.ID, "dimmedLayer")
            if dimmed.is_displayed():
                driver.execute_script("arguments[0].style.display = 'none';", dimmed)
                print("[Kakao] dimmedLayer 제거 완료")
        except NoSuchElementException:
            pass

        # 첫 번째 장소 상세 페이지 이동
        place = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="info.search.place.list"]/li[1]')))
        btn = place.find_element(By.CLASS_NAME, "moreview")
        driver.execute_script("arguments[0].click();", btn)
        print("[Kakao] 상세 페이지로 이동")

        # 새 창 전환
        main = driver.window_handles[0]
        WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) == 2)
        detail = [h for h in driver.window_handles if h != main][0]
        driver.switch_to.window(detail)
        print("[Kakao] 상세 창 포커스 전환")

        # 리뷰 탭 클릭 시도
        try:
            review_tab = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[@class='link_tab' and contains(text(), '후기')]")
            ))
            driver.execute_script("arguments[0].click();", review_tab)
            print("[Kakao] 리뷰 탭 클릭 완료")
            time.sleep(1)
        except TimeoutException:
            print("[Kakao] 리뷰 탭('후기')이 존재하지 않음 → 리뷰 없음으로 처리")
            return []

        # 리뷰 리스트 로딩 확인
        try:
            print("[Kakao] 리뷰 요소 탐색 시도 중...")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.list_review")))
            print("[Kakao] 리뷰 리스트 로딩 성공")

            # 스크롤로 추가 로딩
            for _ in range(3):
                driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
                time.sleep(1)

            items = driver.find_elements(By.CSS_SELECTOR, "ul.list_review > li")
            print(f"[Kakao] 리뷰 항목 개수 탐색됨: {len(items)}")
            items = items[:MAX_REVIEWS]

            reviews = []
            for idx, item in enumerate(items):
                try:
                    # 본문 더보기 클릭
                    try:
                        btn_more = item.find_element(By.CSS_SELECTOR, "span.btn_more")
                        driver.execute_script("arguments[0].click();", btn_more)
                        time.sleep(0.5)
                    except NoSuchElementException:
                        pass

                    # reviewer 추출
                    name_elem = item.find_element(By.CSS_SELECTOR, "span.name_user")
                    raw_name = name_elem.text  # e.g. "리뷰어 이름, Grai"
                    reviewer = raw_name.split(",")[-1].strip()

                    # rating 추출 (span.starred_grade 내 두 번째 screen_out)
                    rating_elem = item.find_element(
                        By.CSS_SELECTOR,
                        "span.starred_grade > span.screen_out:nth-of-type(2)"
                    )
                    rating = rating_elem.text.strip()

                    area = item.find_element(By.CLASS_NAME, "area_review")
                    text = area.find_element(By.CLASS_NAME, "desc_review").text.strip()
                    date = area.find_element(By.CLASS_NAME, "txt_date").text.strip()

                    reviews.append({
                        'platform': 'Kakao',
                        'reviewer': reviewer,
                        'text': text,
                        'rating': rating,
                        'date': date
                    })
                    print(f"[Kakao] 리뷰 {idx + 1} 수집 완료")
                except Exception as review_error:
                    print(f"[Kakao] 리뷰 {idx + 1} 수집 실패: {review_error}")
                    continue

            print(f"[Kakao] 리뷰 수집 완료: {len(reviews)}개")
            return reviews

        except Exception as e:
            print(f"[Kakao] 리뷰 리스트 로딩 실패: {type(e).__name__} - {e}")
            return []

    except Exception as e:
        print(f"[Kakao] 오류 발생: {e}")
        return []

    finally:
        driver.quit()


# --- Google Maps Helper Functions ---
def click_review_tab(driver):
    """리뷰 탭을 찾아 클릭합니다."""
    try:
        tabs = driver.find_elements(By.CSS_SELECTOR, 'button[role="tab"]')
        for t in tabs:
            if "리뷰" in t.text:
                try:
                    t.click()
                except:
                    driver.execute_script("arguments[0].click();", t)
                WebDriverWait(driver, 5).until(
                    lambda d: t.get_attribute("aria-selected") == "true"
                )
                print("[Google] 리뷰 탭 클릭 완료")
                time.sleep(0.5)
                return True
        print("[Google] 리뷰 탭을 찾지 못함")
        return False
    except Exception as e:
        print(f"[Google] 리뷰 탭 클릭 중 오류: {e}")
        return False

def get_top_reviews(driver, topn=MAX_REVIEWS, max_scrolls=12):
    """리뷰 패널에서 최대 topn개의 리뷰를 수집합니다."""
    try:
        panel = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.m6QErb.DxyBCb.kA9KIf.dS8AEf"))
        )
        print("[Google] 리뷰 패널 로딩 완료")
    except TimeoutException:
        print("[Google] 리뷰 패널 로딩 실패: 패널을 찾을 수 없음")
        return []

    seen_ids = set()
    reviews = []
    prev_block_count = 0

    for i in range(max_scrolls):
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", panel)
        time.sleep(2.5)  # 충분한 대기 (JS 로딩 고려)

        blocks = panel.find_elements(By.CSS_SELECTOR, 'div.jftiEf')
        print(f"[Google] 스크롤 {i+1}: {len(blocks)}개의 리뷰 블록 발견")

        # 리뷰 수집
        for blk in blocks:
            rid = blk.get_attribute("data-review-id")
            if not rid or rid in seen_ids:
                continue
            text_elements = blk.find_elements(By.CSS_SELECTOR, "span.wiI7pd")
            if not text_elements:
                continue

            try:
                seen_ids.add(rid)
                writer = blk.find_element(By.CSS_SELECTOR, "div.d4r55").text.strip()
                text = text_elements[0].text.replace("\n", " ").strip()
                star = blk.find_element(By.CSS_SELECTOR, "span.kvMYJc").get_attribute("aria-label").strip()
                date = blk.find_element(By.CSS_SELECTOR, "span.rsqaWe").text.strip()
                reviews.append({
                    'reviewer': writer,
                    'text': text,
                    'rating': star,
                    'date': date
                })
                print(f"[Google] 리뷰 수집: 작성자={writer}, 평점={star}")
            except Exception as e:
                print(f"[Google] 리뷰 블록 처리 중 오류: {e}")
                continue

            if len(reviews) >= topn:
                print(f"[Google] 목표 리뷰 수({topn}) 도달")
                return reviews

        # 종료 조건 변경: 새로 로딩된 리뷰 블록이 없을 경우
        if len(blocks) == prev_block_count:
            print("[Google] 더 이상 새로운 리뷰 블록 없음 (종료)")
            break
        prev_block_count = len(blocks)

    print(f"[Google] 총 {len(reviews)}개 리뷰 수집 완료")
    return reviews

# --- Google Maps Crawling Function ---
def crawl_google_reviews(restaurant_name):
    driver = init_driver(headless=False)
    print(f"[Google] '{restaurant_name}' 검색 시작")
    try:
        driver.get("https://www.google.com/maps")
        wait = WebDriverWait(driver, 10)
        inp = wait.until(EC.presence_of_element_located((By.ID, "searchboxinput")))
        inp.clear()
        inp.send_keys(restaurant_name)
        inp.send_keys(Keys.ENTER)

        # 검색 결과 로딩 대기
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.Nv2PK.THOPZb.CpccDe"))
            )
            print("[Google] 검색 결과 로딩 완료")
        except TimeoutException:
            print("[Google] 검색 결과 로딩 실패: 결과 카드 없음")

        # 첫 번째 검색 결과 카드 찾기
        href = None
        try:
            card = driver.find_element(By.CSS_SELECTOR, "div.Nv2PK.THOPZb.CpccDe")
            a = card.find_element(By.CSS_SELECTOR, "a.hfpxzc")
            href = a.get_attribute("href")
            print("[Google] 첫 번째 결과 카드 찾음 → 상세 페이지 이동")
        except NoSuchElementException:
            print("[Google] 첫 번째 결과 카드 찾기 실패 → 현재 URL로 상세 페이지 이동 시도")
            href = driver.current_url

        # 상세 페이지로 이동
        driver.get(href)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "h1"))
            )
            print("[Google] 상세 페이지 로딩 완료")
        except TimeoutException:
            print("[Google] 상세 페이지 로딩 실패")
            return []

        # 리뷰 탭 클릭
        if not click_review_tab(driver):
            print("[Google] 리뷰 탭을 찾지 못함")
            return []

        # 리뷰 수집
        reviews = get_top_reviews(driver, topn=MAX_REVIEWS)
        for review in reviews:
            review['platform'] = 'Google'
        print(f"[Google] 리뷰 수집 완료: {len(reviews)}개")
        return reviews

    except Exception as e:
        print(f"[Google] 오류 발생: {e}")
        return []

    finally:
        driver.quit()


# --- Naver Map Functions ---
def crawl_reviews(driver, section, max_reviews=MAX_REVIEWS):
    """
    "더보기" 버튼을 반복 클릭해 지정된 개수만큼 리뷰를 로드하고, 리뷰 텍스트와 날짜를 반환합니다.
    """
    clicks = 0
    # 반복 클릭하여 더 많은 리뷰 로드
    while True:
        items = section.find_elements(By.CSS_SELECTOR, "ul > li")
        if len(items) >= max_reviews:
            break
        try:
            more_btn = section.find_element(By.XPATH, ".//a[.//span[text()='더보기']]")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", more_btn)
            # JS 클릭으로 오버레이 문제 방지
            driver.execute_script("arguments[0].click();", more_btn)
            clicks += 1
            time.sleep(1)
        except (NoSuchElementException, TimeoutException):
            break

    # 로드된 리뷰 요소 재획득
    items = section.find_elements(By.CSS_SELECTOR, "ul > li")
    reviews = []
    for idx, item in enumerate(items[:max_reviews], start=1):
        try:
            author = item.find_element(By.CSS_SELECTOR, "div.pui__JiVbY3 span span").text
            date_elem = item.find_element(By.TAG_NAME, "time")
            # datetime 속성 우선, 없으면 text
            date = date_elem.get_attribute("datetime") or date_elem.text.strip()
            text = item.find_element(By.CSS_SELECTOR, "div.pui__vn15t2 > a").text
            reviews.append({'platform':'Naver','reviewer':author,'text':text,'rating':None,'date':date})
            print(f"[Naver] 리뷰 {idx} 수집 완료: 작성자={author}, 날짜={date}")
        except NoSuchElementException:
            print(f"[Naver] 리뷰 {idx} 수집 실패: 요소 누락")
            continue
    print(f"[Naver] 리뷰 수집 완료: {len(reviews)}개")
    return reviews


def crawl_naver_reviews(restaurant_name):
    """
    주어진 식당 이름으로 Naver Map v5에서 리뷰를 최대 MAX_REVIEWS개까지 수집합니다.
    """
    driver = init_driver()
    wait = WebDriverWait(driver, 15)
    print(f"[Naver] '{restaurant_name}' 검색 시작")
    try:
        driver.get("https://map.naver.com/v5")
        time.sleep(2)
        # 가끔 떠 있는 모달/오버레이 제거
        driver.execute_script(
            "document.querySelectorAll('div.modal_layer, div.dimmedLayer').forEach(el => el.style.display='none');"
        )
        # 검색 입력
        try:
            sb = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.input_search")))
        except TimeoutException:
            sb = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[placeholder*='장소']")))
        sb.clear()
        sb.send_keys(restaurant_name, Keys.ENTER)
        print("[Naver] 검색어 전송 완료")
        time.sleep(2)

        # 검색 결과 iframe 전환
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "iframe#searchIframe")))
        time.sleep(1)
        # 첫 번째 결과 클릭
        first_li = wait.until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "#_pcmap_list_scroll_container > ul > li:nth-child(1)"
            ))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", first_li)
        time.sleep(0.5)
        # JS 클릭으로 가려짐 이슈 해결
        driver.execute_script("arguments[0].click();", first_li.find_element(By.TAG_NAME, "a"))
        print("[Naver] 첫 번째 결과 클릭 완료")
        time.sleep(2)

        # 상세 페이지 iframe 진입
        driver.switch_to.default_content()
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "iframe#entryIframe")))
        time.sleep(1)
        # 리뷰 탭 클릭 (JS 클릭)
        review_tab = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//a[.//span[text()='리뷰']]") )
        )
        driver.execute_script("arguments[0].click();", review_tab)
        print("[Naver] 리뷰 탭 클릭 완료")
        time.sleep(1)

        # 리뷰 섹션 로딩 및 수집
        section = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.place_section.k1QQ5")))
        return crawl_reviews(driver, section)

    except Exception as e:
        print(f"[Naver] 오류 발생: {e}")
        return []
    finally:
        driver.quit()
# --- 크롤링 함수들 정의 끝 ---
