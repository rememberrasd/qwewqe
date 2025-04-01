from selenium import webdriver
from selenium.common.exceptions import ElementClickInterceptedException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver import ActionChains
from datetime import datetime, timedelta
from get_tweet import *
from twiiiiter import *
import re
import traceback
import time
import yaml
import random
from random import randint
from typing import List, Dict, Any
import pytz
from zoneinfo import ZoneInfo
from utils.logger_config import logger, tr_timezone
from utils.rate_limiter import TwitterRateLimiter
from utils.logger_config import logger, tr_timezone


tr_timezone = pytz.timezone('Europe/Istanbul')

def get_dynamic_wait_time(base_wait=5):
    """Dinamik bekleme süresi hesaplar"""
    return randint(base_wait, base_wait * 3)

def wait_for_element_visibility(selenium_session, css_selector):
    wait = WebDriverWait(selenium_session.driver, 15)
    element = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
    )
    
    # JavaScript ile görünürlük kontrolü
    is_visible = selenium_session.driver.execute_script(
        "return window.getComputedStyle(arguments[0]).visibility !== 'hidden'", 
        element
    )
    return element if is_visible else None

def scroll_into_view(selenium_session, element):
    selenium_session.driver.execute_script(
        "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", 
        element
    )
    time.sleep(1)  # Scroll animasyonunun tamamlanmasını bekleyin

def wait_for_element_ready(selenium_session, css_selector):
    wait = WebDriverWait(selenium_session.driver, 15)
    return wait.until(
        EC.all_of(
            EC.presence_of_element_located((By.CSS_SELECTOR, css_selector)),
            EC.visibility_of_element_located((By.CSS_SELECTOR, css_selector)),
            EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
        )
    )

def ensure_element_visible(driver, element, wait_time=15):
    """Elementin görünür olmasını sağlar"""
    wait = WebDriverWait(driver, wait_time)
    try:
        # Elementi görünür hale getir
        driver.execute_script(
            "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", 
            element
        )
        # Elementin görünür olmasını bekle
        wait.until(EC.visibility_of(element))
        return True
    except:
        return False

def remove_days(days_to_remove):
    if days_to_remove < 0:
        days_to_remove = 0
    
    date_format = "%Y-%m-%d"
    today_date = datetime.now().strftime("%Y-%m-%d")
    current_date = datetime.strptime(today_date, date_format)
    new_date = current_date - timedelta(days=days_to_remove)
    
    return(new_date.strftime(date_format))

def parse_number(num):
    num = str(num)
    if "B" in num:
        if "." in num:
            num  = num.replace(".","").replace("B","")
            num  = num + "00000000"
            
        else:
            num = num.replace("B","")
            num  = num + "000000000"
            
    elif "M" in num:
        if "." in num:
            num  = num.replace(".","").replace("M","")
            num  = num + "00000"

        else:
            num = num.replace("B","")
            num  = num + "000000"
    
    elif "K" in num:
        if "." in num:
            num  = num.replace(".","").replace("K","")
            num = num + "00"
        else:
            num = num.replace("K","")
            num = num + "000"
    else:
        if "." in num:
            num  = num.replace(".","")
    
    if "," in num:
        num = num.replace(",","")
    
    return int(num)

def convert_string_to_date(date_string):
    original_date = datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S")
    new_date = original_date + timedelta(hours=2)
    return (new_date)

def are_last_x_elements_same(lst,x):
    lst_2 = []
    if len(lst) < x:
        return False
    if len(lst) >= x:
        lst.reverse()
        for i in range(0,x):
            l = lst[i]
            if l not in lst_2 and len(lst_2) != 0:
                return False
            else:
                lst_2.append(l)
    return True

def check_elem_on_a_list(elem_, list_):
    return next((l for l in list_ if elem_ in l.lower()), elem_)

def parse_tweet_date(date_str):
    """
    Tweet'ten alınan tarih string'ini datetime objesine çevirir
    """
    try:
        # Gelen string'i temizle
        date_str = date_str.strip().replace('"', '')
        # Twitter'ın UTC formatındaki tarihi parse et
        return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
    except Exception as e:
        logger.error(f"date parse error: {str(e)}")
        return None

def is_tweet_in_date_range(tweet_date_str, max_days):
    """Tweet'in son 'max_days' gün içinde olup olmadığını kontrol eder."""
    try:
        tweet_date = datetime.strptime(tweet_date_str, '%Y-%m-%d %H:%M:%S')
        since_date = datetime.utcnow() - timedelta(days=max_days)
        if tweet_date >= since_date:
            return True
        else:
            logger.info(f"Tweet tarihi {tweet_date_str} son {max_days} gün içinde değil.")
            return False
    except Exception as e:
        logger.error(f"Date range check error for '{tweet_date_str}': {e}")
        return False

def load_config():
    try:
        with open("configuration.yml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)  # YAML'ı dict olarak yükle
        if not isinstance(config, dict):
            raise ValueError("configuration.yml file is not in dictionary format.")
        return config
    except Exception as e:
        logger.error(f"error loading config: {e}")
        return None  # Hata varsa None döndür

def extract_keyword(query):
    """Sorgudan tam anahtar kelimeyi çıkarır."""
    # Filtreler ve yasaklı kelimelerden önceki kısmı al
    parts = query.split()
    keyword_parts = []
    for part in parts:
        if (part.startswith("min_faves:") or part.startswith("min_retweets:") or 
            part.startswith("since:") or part.startswith("-")):
            break
        keyword_parts.append(part)
    return " ".join(keyword_parts) if keyword_parts else ""

def is_valid_tweet(tweet):
    """Tweet'in formatını ve içeriğini doğrular."""
    if not isinstance(tweet, dict):
        logger.error("invalid tweet format: dict expected.")
        return False
    if 'text' not in tweet or not isinstance(tweet['text'], str):
        logger.error("invalid tweet structure: 'text' key is missing or wrong type.")
        return False
    return True

def is_valid_giveaway(tweet, search_keyword, blacklist):
    """Tweet'in, sadece anahtar kelimeyle eşleşip eşleşmediğini ve yasaklı kelime içerip içermediğini kontrol eder."""
    if not is_valid_tweet(tweet):
        return False

    try:
        tweet_text = tweet['text'].strip()
        normalized_tweet = normalize_text(tweet_text)
        normalized_keyword = normalize_text(search_keyword)

        # 1. Anahtar kelime kontrolü: Kelime metinde herhangi bir yerde geçmeli
        if normalized_keyword not in normalized_tweet:
            logger.warning(f"current tweet contains keyword: '{search_keyword}' (text: '{normalized_tweet}')")
            return False
        logger.success(f"current tweet found: '{search_keyword}' is present in the text.")

        # 2. Yasaklı kelimeler için kontrol
        for term in blacklist:
            normalized_term = normalize_text(term)
            ban_pattern = re.compile(r'\b' + re.escape(normalized_term) + r'\b')
            if ban_pattern.search(normalized_tweet):
                logger.warning(f"current tweet contains blacklisted keyword: '{term}'")
                return False

        return True

    except Exception as e:
        logger.error(f"Giveaway doğrulama sırasında hata oluştu: {e}")
        return False

import time
from random import randint
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

def clear_cache(driver):
    driver.execute_script("window.localStorage.clear();")
    driver.execute_script("window.sessionStorage.clear();")
    driver.execute_script("caches.keys().then(function(names) { for (let name of names) caches.delete(name); });")

def search_tweet(selenium_session, query="hello", nb_of_tweet_to_search=100, latest=False, d=None, rate_limiter=None):
    if rate_limiter is None:
        current_username = getattr(selenium_session, 'username', "default_user")
        rate_limiter = TwitterRateLimiter(current_username)
    start_time = time.time()
    max_retries = 3
    
    search_keyword = extract_keyword(query)
    if not search_keyword:
        logger.error("Failed to extract keyword from query.")
        return []

    logger.info("\n" + "="*50)
    logger.info(f"Search query: {query}")
    logger.info(f"Search keyword: {search_keyword}")
    logger.info("="*50)
    
    data_list = []
    tweet_info_dict = {
        "username": "",
        "text": "",
        "id": 0,
        "url": "",
        "date": "",
        "like": 0,
        "retweet": 0,
        "reply": 0
    }
    scroll_pause_time = random.randint(2, 4)
    max_scroll_attempts = 20
    
    if d is None:
        d = Data()
        logger.info("Default data object created")

    def attempt_search(attempt, d, rate_limiter):
        nonlocal data_list
        try:
            if not rate_limiter.can_perform_action("search"):
                wait_time = rate_limiter.get_wait_time("search")
                logger.info(f"Arama için hız sınırı aşıldı, {wait_time} saniye bekleniyor...")
                time.sleep(wait_time)
                return attempt_search(attempt + 1, d, rate_limiter)
            
            selenium_session.driver.get("https://x.com/home")
            wait = WebDriverWait(selenium_session.driver, 30)
            wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
            logger.info(f"Attempt {attempt}: Home page loaded")
            
            # WebDriver bağlantısını kontrol et
            if not selenium_session.driver.service.is_connectable():
                logger.error("WebDriver bağlantısı kopmuş.")
                return []
            
            since_date = (datetime.utcnow() - timedelta(days=d.maximum_day)).strftime('%Y-%m-%d')
            
            logger.info("\n" + "="*50)
            logger.info("Home page search started")
            logger.info("="*50)

            # Sayfanın yüklenmesini tekrar kontrol et ve last_height al
            wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
            try:
                last_height = selenium_session.driver.execute_script("return document.body.scrollHeight")
            except Exception as e:
                logger.error(f"execute_script hatası: {str(e)}")
                # Alternatif yöntem
                try:
                    body_element = selenium_session.driver.find_element(By.TAG_NAME, "body")
                    last_height = body_element.size["height"]
                except Exception as e:
                    logger.error(f"Alternatif yöntem hatası: {str(e)}")
                    return []
            
            home_scroll_attempt = 0
            
            while len(data_list) < nb_of_tweet_to_search and home_scroll_attempt < 5:
                new_tweets = selenium_session.driver.execute_script("""
                    const minFaves = arguments[0];
                    const minRetweets = arguments[1];
                    const sinceDate = new Date(arguments[2]);
                    const blacklist = arguments[3];
                    const query = arguments[4].toLowerCase();

                    function parseNumber(text) {
                        if (!text) return 0;
                        return parseInt(text.replace(',', '')) || 0;
                    }

                    function normalizeText(text) {
                        return text.toLowerCase().replace(/\s*[xX]\s*/g, 'x').replace(/[\$,]/g, '');
                    }

                    function isTweetValid(tweetText, likeCount, retweetCount, tweetDate) {
                        const normalizedTweet = normalizeText(tweetText);
                        const normalizedQuery = normalizeText(query);
                        if (!normalizedTweet.includes(normalizedQuery)) return false;
                        if (likeCount < minFaves || retweetCount < minRetweets) return false;
                        const tweetDateObj = new Date(tweetDate);
                        const sinceDateObj = new Date(sinceDate);
                        if (tweetDateObj < sinceDateObj) return false;
                        const lowerTweetText = tweetText.toLowerCase();
                        for (const term of blacklist) {
                            const normalizedTerm = normalizeText(term);
                            const banPattern = new RegExp(`\\b${normalizedTerm}\\b`);
                            if (banPattern.test(lowerTweetText)) return false;
                        }
                        return true;
                    }

                    function collectTweets() {
                        const tweets = [];
                        const tweetElements = document.querySelectorAll('[data-testid="tweet"]');
                        tweetElements.forEach(tweet => {
                            try {
                                const tweetTextElement = tweet.querySelector('[data-testid="tweetText"]');
                                if (!tweetTextElement) return;
                                const tweetText = tweetTextElement.innerText;
                                const timeElement = tweet.querySelector('time');
                                if (!timeElement) return;
                                const tweetDate = timeElement.getAttribute('datetime');
                                const likeElement = tweet.querySelector('[data-testid="like"]') || tweet.querySelector('[data-testid="unlike"]');
                                const retweetElement = tweet.querySelector('[data-testid="retweet"]');
                                const likeCount = parseNumber(likeElement ? likeElement.innerText : "0");
                                const retweetCount = parseNumber(retweetElement ? retweetElement.innerText : "0");
                                if (isTweetValid(tweetText, likeCount, retweetCount, tweetDate)) {
                                    const statusElement = tweet.querySelector('[href*="/status/"]');
                                    const userElement = tweet.querySelector('[href*="/"]');
                                    if (statusElement && userElement) {
                                        tweets.push({
                                            username: userElement.innerText,
                                            text: tweetText,
                                            id: statusElement.getAttribute('href').split('/').pop(),
                                            url: statusElement.href,
                                            date: tweetDate,
                                            likes: likeCount,
                                            retweets: retweetCount
                                        });
                                    }
                                }
                            } catch (error) {
                                console.error(`Tweet işlenirken hata: ${error}`);
                            }
                        });
                        return tweets;
                    }
                    return collectTweets();
                """, d.minimum_like, d.minimum_rt, since_date, d.giveaway_to_blacklist, search_keyword)
                
                for tweet in new_tweets:
                    tweet_info_dict = {
                        "username": tweet['username'],
                        "text": tweet['text'],
                        "id": tweet['id'],
                        "url": tweet['url'],
                        "date": tweet['date'],
                        "like": tweet['likes'],
                        "retweet": tweet['retweets'],
                        "reply": 0
                    }
                    if is_valid_giveaway(tweet_info_dict, search_keyword, d.giveaway_to_blacklist):
                        if tweet_info_dict not in data_list:
                            data_list.append(tweet_info_dict)
                            logger.info(f"[{datetime.now(ZoneInfo('Europe/Istanbul')).strftime('%Y-%m-%d %H:%M:%S')}] Home page new tweet found: {tweet_info_dict['url']}")

                selenium_session.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(scroll_pause_time)
                new_height = selenium_session.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    home_scroll_attempt += 1
                else:
                    home_scroll_attempt = 0
                    last_height = new_height

                if time.time() - start_time > 15:
                    break

            logger.info(f"\n[{datetime.now(ZoneInfo('Europe/Istanbul')).strftime('%Y-%m-%d %H:%M:%S')}] Home page total tweets: {len(data_list)}")

            if len(data_list) < nb_of_tweet_to_search:
                if not rate_limiter.can_perform_action("search"):
                    wait_time = rate_limiter.get_wait_time("search")
                    logger.info(f"Arama kutusu için hız sınırı aşıldı, {wait_time} saniye bekleniyor...")
                    time.sleep(wait_time)
                    return attempt_search(attempt + 1, d, rate_limiter)
                logger.info("\n" + "="*50)
                logger.debug(f"Attempt {attempt}: Search box search started")
                logger.info("="*50)

                selenium_session.driver.get("https://x.com/explore")
                wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
                logger.info(f"Attempt {attempt}: Explore page loaded")
                
                input_box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="SearchBox_Search_Input"]')))
                for _ in range(3):
                    try:
                        input_box.click()
                        break
                    except ElementClickInterceptedException:
                        time.sleep(1)
                input_box.send_keys(query)
                input_box.send_keys(Keys.ENTER)
                logger.info(f"Attempt {attempt}: Search query sent")
                time.sleep(random.randint(5, 10))
                
                if latest:
                    current_url = selenium_session.driver.current_url
                    selenium_session.driver.get(current_url + "&f=live")
                    logger.info("Search box latest tweets filter applied")
                    time.sleep(random.randint(5, 10))

                # Sayfanın yüklenmesini tekrar kontrol et ve last_height al
                wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
                try:
                    last_height = selenium_session.driver.execute_script("return document.body.scrollHeight")
                except Exception as e:
                    logger.error(f"execute_script hatası: {str(e)}")
                    # Alternatif yöntem
                    try:
                        body_element = selenium_session.driver.find_element(By.TAG_NAME, "body")
                        last_height = body_element.size["height"]
                    except Exception as e:
                        logger.error(f"Alternatif yöntem hatası: {str(e)}")
                        return []
                
                scroll_attempt = 0
                
                while len(data_list) < nb_of_tweet_to_search and scroll_attempt < max_scroll_attempts:
                    selenium_session.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(scroll_pause_time)
                    selenium_session.driver.execute_script("window.scrollBy(0, -100);")
                    time.sleep(2)
                    selenium_session.driver.execute_script("window.scrollBy(0, 100);")
                    
                    new_height = selenium_session.driver.execute_script("return document.body.scrollHeight")
                    tweets_info = selenium_session.driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweet"]')
                    tweets_text = selenium_session.driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweetText"]')
                    
                    for tweet_info, tweet_text in zip(tweets_info, tweets_text):
                        try:
                            tweet_content = tweet_text.text if tweet_text else ""
                            normalized_tweet = tweet_content.lower()
                            search_keyword_normalized = search_keyword.lower()

                            if search_keyword_normalized not in normalized_tweet:
                                logger.warning(f"{search_keyword} not found in tweet: {repr(tweet_content)}")
                                continue

                            if not is_valid_giveaway({"text": tweet_content}, search_keyword, d.giveaway_to_blacklist):
                                continue

                            wait = WebDriverWait(selenium_session.driver, 10)
                            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweet"]')))

                            try:
                                like_element = tweet_info.find_element(By.CSS_SELECTOR, '[data-testid="like"]')
                                like_count = int(like_element.text.replace(',', '')) if like_element.text else 0
                            except NoSuchElementException:
                                try:
                                    unlike_element = tweet_info.find_element(By.CSS_SELECTOR, '[data-testid="unlike"]')
                                    like_count = int(unlike_element.text.replace(',', '')) if unlike_element.text else 0
                                    logger.info("Tweet zaten beğenilmiş.")
                                except NoSuchElementException:
                                    logger.error("Beğeni veya beğeniyi kaldırma butonu bulunamadı.")
                                    continue

                            try:
                                retweet_element = tweet_info.find_element(By.CSS_SELECTOR, '[data-testid="retweet"]')
                                retweet_count = int(retweet_element.text.replace(',', '')) if retweet_element.text else 0
                            except NoSuchElementException:
                                try:
                                    unretweet_element = tweet_info.find_element(By.CSS_SELECTOR, '[data-testid="unretweet"]')
                                    retweet_count = int(unretweet_element.text.replace(',', '')) if unretweet_element.text else 0
                                    logger.info("Tweet zaten retweet edilmiş.")
                                except NoSuchElementException:
                                    logger.warning("Retweet veya retweeti kaldırma butonu bulunamadı, retweet sayısı 0.")
                                    retweet_count = 0

                            if like_count < 50 or retweet_count < 50:
                                logger.info(f"Tweet atlandı: beğeni={like_count}, retweet={retweet_count}")
                                continue

                            tweet_date = tweet_info.find_element(By.CSS_SELECTOR, 'time').get_attribute('datetime').replace('T', ' ').replace('.000Z', '')
                            if not is_tweet_in_date_range(tweet_date, max_days=d.maximum_day):
                                continue

                            tweet_link = tweet_info.find_element(By.CSS_SELECTOR, '[href*="/status/"]').get_attribute('href')
                            tweet_info_dict = {
                                "username": tweet_info.find_element(By.CSS_SELECTOR, '[href*="/"]').text,
                                "text": tweet_content,
                                "id": tweet_link.split('/status/')[1],
                                "url": tweet_link,
                                "date": tweet_date,
                                "like": like_count,
                                "retweet": retweet_count,
                                "reply": 0
                            }
                            if tweet_info_dict not in data_list:
                                data_list.append(tweet_info_dict)
                                logger.info(f"Geçerli tweet bulundu: {tweet_link}")

                        except Exception as e:
                            logger.error(f"Tweet işleme hatası: {str(e)}")
                            continue

                    if new_height == last_height:
                        scroll_attempt += 1
                    else:
                        scroll_attempt = 0
                        last_height = new_height

                    if time.time() - start_time > 30:
                        logger.warning("Zaman sınırı aşıldı (30 saniye)")
                        break

            logger.info("\n" + "="*50)
            logger.info(f"Toplam tweet sayısı: {len(data_list)}")
            logger.info("Arama tamamlandı")
            logger.info("="*50)
            
            if len(data_list) > nb_of_tweet_to_search:
                return data_list[:nb_of_tweet_to_search]
            return data_list

        except Exception as e:
            logger.error("\n" + "="*50)
            logger.error(f"Attempt {attempt}: Tweet arama hatası: {str(e)}")
            logger.error("="*50)
            if attempt < max_retries:
                if not rate_limiter.can_perform_action("search"):
                    wait_time = rate_limiter.get_wait_time("search")
                    logger.info(f"Hız sınırı nedeniyle {wait_time} saniye bekleniyor...")
                    time.sleep(wait_time)
                logger.info("Sayfa yenileniyor ve oturum kontrol ediliyor...")
                while True:
                    clear_cache(selenium_session.driver)
                    selenium_session.driver.execute_script("window.location.reload(true);")
                    time.sleep(5)
                    try:
                        wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
                        if selenium_session.driver.find_element(By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'):
                            logger.info("Sayfa başarıyla yüklendi.")
                            break
                    except TimeoutException:
                        logger.warning("Sayfa tam olarak yüklenemedi, yeniden yüklemeye devam ediliyor...")
                    except NoSuchElementException:
                        logger.warning("Sayfa tam olarak yüklenemedi, yeniden yüklemeye devam ediliyor...")
                return attempt_search(attempt + 1, d, rate_limiter)
            return data_list

    return attempt_search(1, d, rate_limiter)

def get_trend(selenium_session, search_word=None, limit=None):
    """
    Twitter'dan trend konularını veya belirli bir arama sonucunu getirir.
    
    Args:
        selenium_session: Selenium oturumu
        search_word: Aranacak kelime (opsiyonel)
        limit: Getirilecek tweet sayısı limiti (opsiyonel)
    
    Returns:
        List: Eğer search_word None ise trend listesi, 
              değilse bulunan tweetlerin listesi
    """
    try:
        wait = WebDriverWait(selenium_session.driver, 15)
        
        if search_word is None:
            logger.info("getting trend topics...")
            selenium_session.driver.get("https://x.com/explore")
            
            wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
            logger.info("explore page loaded")
            
            trends = wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[data-testid="trend"]'))
            )
            
            trends_list = []
            for trend in trends:
                if ensure_element_visible(selenium_session.driver, trend):
                    trends_list.append(trend.text.split("\n")[1])
                    
            logger.info(f"total {len(trends_list)} found trending topic")
            return trends_list
        else:
            # Arama sonuçlarını getir
            search_url = f"https://x.com/search?q={search_word}&src=typed_query&f=live"
            logger.info(f"'{search_word}' search is underway for")
            selenium_session.driver.get(search_url)
            
            # Sayfa yüklenmesini bekle
            wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
            logger.info(f"'{search_word}' the search page for")
            
            # Tweetleri bul
            tweets = wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[data-testid="tweet"]'))
            )
            
            tweet_list = []
            for tweet in tweets[:limit or 10]:  # Limit yoksa varsayılan 10 tweet
                if ensure_element_visible(selenium_session.driver, tweet):
                    # Tweet URL'sini bul
                    try:
                        link = tweet.find_element(By.CSS_SELECTOR, 'a[href*="/status/"]').get_attribute("href")
                        tweet_list.append({"url": link})
                        logger.debug(f"tweet url added: {link}")
                    except Exception as e:
                        logger.warning(f"tweet url could not be obtained: {str(e)}")
                        continue
            
            logger.info(f"'{search_word}' for {len(tweet_list)} tweet found")
            return tweet_list
            
    except Exception as e:
        logger.error(f"search failed: {str(e)}")
        return []

def search_tweet_for_better_rt(selenium_session):
    """
    Daha iyi retweetler için tweet arar.

    Args:
        selenium_session: Selenium oturumu
        
    Returns:
        List[str]: Bulunan tweetlerin listesi
    """
    try:
        logger.info("\n" + "="*50)
        logger.info(f"[rt arama] başlangıç: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        d = Data()
        with open("configuration.yml", "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

        nb = data["random_retweet_nb"]
        random_action = data["random_action"]
        word_to_rt = data["word_to_rt"]
        rt_your_word = data["rt_your_word"]
        rt_to_blacklist = data["rt_to_blacklist"]
        url_list = []

        logger.info(f"[configuration] rt number: {nb}")
        logger.info(f"[configuration] random action: {random_action}")
        logger.info(f"[configuration] rt word list: {len(word_to_rt)} word")

        if random_action == True and nb > 0:
            nb = randint(1, nb)
            logger.info(f"[info] random rt number set: {nb}")

        trends = get_trend(selenium_session)
        if not trends:
            logger.error("trend topics not found. search process canceled.")
            return []

        if not random_action:
            if not rt_your_word:
                logger.info("looking for rt from trending topics")
                search_word = trends[0]
                tweet_found = get_trend(selenium_session, search_word, nb)
                for tweet in tweet_found:
                    if tweet["url"] not in url_list and not any(r in tweet["url"] for r in rt_to_blacklist):
                        url_list.append(tweet["url"])
                        logger.info(f"added new tweet: {tweet['url']}")
            else:
                search_word = word_to_rt[randint(0, len(word_to_rt) - 1)]
                logger.info(f"[search] selected word: {search_word}")
                tweet_found = get_trend(selenium_session, search_word, nb)
                for tweet in tweet_found:
                    if tweet["url"] not in url_list and not any(r in tweet["url"] for r in rt_to_blacklist):
                        url_list.append(tweet["url"])
                        logger.info(f"added new tweet: {tweet['url']}")
        else:
            if rt_your_word:
                trends = word_to_rt if word_to_rt else get_trend(selenium_session)
                if not word_to_rt:
                    logger.info("[info] empty word list, going to trend topics")
                    
            for _ in range(nb):
                search_word = trends[randint(0, len(trends) - 1)]
                logger.info(f"[search] selected word: {search_word}")
                tweet_found = get_trend(selenium_session, search_word, 1)
                for tweet in tweet_found:
                    if tweet["url"] not in url_list and not any(r in tweet["url"] for r in rt_to_blacklist):
                        url_list.append(tweet["url"])
                        logger.info(f"added new tweet: {tweet['url']}")

        logger.info("\n" + "="*50)
        logger.info(f"[result] found tweet number: {len(url_list)}")
        logger.info(f"[result] end time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*50)
        return url_list

    except Exception as e:
        logger.error("\n" + "="*50)
        logger.error("rt search operation failed")
        logger.error(f"detail: {str(e)}")
        logger.error(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.error("="*50)
        return []       

# Tweet elementlerini toplu işleme almak için
def process_tweets_batch(tweets, wait_time=0.5):
    """Tweet'leri batch halinde işler"""
    for tweet in tweets:
        if ensure_element_visible(selenium_session.driver, tweet):
            yield tweet
        time.sleep(wait_time)                

def list_inside_text(list_one,text):
    for l in list_one:
        if l.lower() not in text.lower():
            return False
    return True

def reset_file(file_path):
    """Dosyayı sıfırlar"""
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write('')

def get_giveaway_url(selenium_session):
    """
    Çekiliş URL'lerini bulup getiren fonksiyon.
    
    Args:
        selenium_session: Selenium oturumu
        
    Returns:
        list: Bulunan çekiliş URL'lerinin listesi
    """
    start_time = time.time()
    current_time = datetime.now(tr_timezone)    
    logger.info(f"{current_time.strftime('%Y-%m-%d %H:%M:%S')}")    
    
    try:
        d = Data()
        # Dosyaları sıfırla ve hazırla
        reset_file("recent_url.txt")
        reset_file("url.txt")
        
        # Tweet ve takip edilecek bilgileri için listeler
        tweets_url = []
        
        # Sayaç ve kontrol değişkenleri
        nb_of_giveaway_found = 0
        doublon = 0
        
        # URL'leri dosyadan oku
        url_from_file = print_file_info("url.txt").split("\n")
        
        # Ayarlar ve limitler
        MAX_GIVEAWAYS = 250
        
        # Rate limit kontrolü için bekleme süresi
        rate_limit_pause = random.randint(5, 10)
        logger.info(f"rate limit pause: {rate_limit_pause} seconds")
        time.sleep(rate_limit_pause)

        # Yasaklı kelimeleri işle
        ban_word = ""
        for banned_word in d.giveaway_to_blacklist:
            if "." not in banned_word:
                ban_word += f"-{banned_word} "

        if len(ban_word) <= len(d.giveaway_to_blacklist):
            ban_word = ""
            
        # Tweet arama limitini dinamik olarak ayarla
        nb_of_tweet_to_search = d.max_giveaway
        d.nb_of_giveaway = min(d.nb_of_giveaway, MAX_GIVEAWAYS)  # Toplam çekiliş limiti korunuyor

        # Her bir arama kelimesi için tweet ara
        for search_word in d.to_be_added_to_search:
            if not search_word.strip():  # Boş search_word'leri atla
                continue
                
            logger.info(f" searched word {search_word}")
            logger.info(f" current number of giveaways found: {nb_of_giveaway_found}")
            
            # Çekiliş limiti ve geçerlilik kontrolü
            if nb_of_giveaway_found >= d.nb_of_giveaway or "." in search_word:
                continue
                
            # Arama sorgusunu oluştur
            text = (
                f"{search_word} lang:{d.tweet_lang} min_faves:{d.minimum_like} "
                f"min_retweets:{d.minimum_rt} since:{remove_days(d.maximum_day)} {ban_word}"
            )
            
            if d.tweet_lang == "any":
                text = (
                    f"{search_word} min_faves:{d.minimum_like} min_retweets:{d.minimum_rt} "
                    f"since:{remove_days(d.maximum_day)} {ban_word}"
                )

            logger.info(f"search query: {text}")
            
            # Tweet ara
            giveaway_tweets = search_tweet(selenium_session, text, nb_of_tweet_to_search, True)

            if not giveaway_tweets:
                logger.warning("rate limit reason, waiting...")
                time.sleep(rate_limit_pause)
                continue

            # Bulunan tweetleri işle
            for tweet in giveaway_tweets:
                # Tweet'in içeriğinde sadece şu anki search_word var mı kontrol et
                if is_valid_giveaway(tweet, search_word, d.giveaway_to_blacklist):  # blacklist parametresi eklendi
                    if (tweet["url"] not in tweets_url 
                        and tweet["url"] not in url_from_file 
                        and nb_of_giveaway_found < d.nb_of_giveaway):
                        tweets_url.append(tweet["url"])
                        nb_of_giveaway_found += 1
                    else:
                        doublon += 1

                    if nb_of_giveaway_found >= d.nb_of_giveaway:
                        break

            # Dinamik bekleme süresi
            wait_time = random.randint(5, 10)
            time.sleep(wait_time)

            if nb_of_giveaway_found >= d.nb_of_giveaway:
                break

        # Bulunan URL'leri dosyalara kaydet
        with open("url.txt", 'a', encoding='utf-8') as file:
            for url in tweets_url:
                file.write(f"{url}\n")
                
        with open("recent_url.txt", 'a', encoding='utf-8') as file:
            for url in tweets_url:
                file.write(f"{url}\n")

        # Sonuçları raporla
        logger.info(f"total number of giveaways found: {nb_of_giveaway_found}")
        logger.info(f"doublon: {doublon}")
        
        if nb_of_giveaway_found > 0:
            logger.success("search operation completed, bot giveaways will start.")
        else:
            logger.info("search operation completed, no giveaways found.")

        return tweets_url

    except Exception as e:
        logger.error(f"Hata: search operation failed: {str(e)}")
        traceback.print_exc()  # Detaylı hata raporu
        return []