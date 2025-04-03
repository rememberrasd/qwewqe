import yaml
import time
import pytz
import json
import os
import feedparser
import yaml
import random
from selenium.common.exceptions import ElementClickInterceptedException
from datetime import datetime, timezone, timedelta
from random import randint
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    WebDriverException,
    NoSuchElementException
)
from webdriver_manager.chrome import ChromeDriverManager
from utils.logger_config import logger, tr_timezone
from utils.rate_limiter import TwitterRateLimiter
from get_tweet import process_tweet_requirements

# Konfigürasyon yükle
try:
    with open('configuration.yml', 'r', encoding='utf-8') as file:
        data = yaml.safe_load(file)
except Exception as e:
    logger.error(f"konfigürasyon dosyası yüklenemedi: {e}")
    data = {}

# Local application imports
from search import search_tweet_for_better_rt, get_giveaway_url
from get_tweet import *
from utils.rate_limiter import TwitterRateLimiter

# Global sabitler
tr_timezone = pytz.timezone('Europe/Istanbul')
PAGE_LOAD_TIMEOUT = 30

class Scraper:
    def __init__(self, username=None):
        self.username = username

        # Temel ayarlar
        self.cookie_accepted = False
        self.notification_accepted = False
        self.wait_time = random.randint(5, 10)
        self.headless = data.get("headless", False)

        # Chrome options
        self.options = Options()
        if self.headless:
            self.options.add_argument('--headless')
            logger.debug("headless mode active")
            
        # Chrome ayarları
        self.options.add_argument('--log-level=3')
        self.options.add_argument('--silent')
        self.options.add_argument('--disable-logging')
        self.options.add_argument('--disable-dev-shm-usage')
        self.options.add_argument('--no-sandbox')
        self.options.add_argument('--disable-gpu')
        self.options.add_argument('--disable-extensions')
        self.options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        try:
            self.driver = webdriver.Chrome(
                service=ChromeService(ChromeDriverManager().install()), 
                options=self.options
            )
            logger.info("chrome driver successfully initialized")
        except Exception as e:
            logger.error(f"failed to initialize chrome driver: {str(e)}")
            raise

    def wait_for_page_load(self, timeout=20):
        """Sayfanın tamamen yüklenmesini bekler"""
        try:
            # document.readyState kontrolü
            WebDriverWait(self.driver, timeout).until(
                lambda driver: driver.execute_script('return document.readyState') == 'complete'
            )
            
            # jQuery kontrolü
            jquery_complete = """
            try {
                if (typeof jQuery != 'undefined') {
                    return jQuery.active == 0;
                }
                return true;
            } catch(e) {
                return true;
            }
            """
            WebDriverWait(self.driver, timeout).until(
                lambda driver: driver.execute_script(jquery_complete)
            )
            
            time.sleep(3)
            return True
            
        except Exception as e:
            logger.error(f"page load error: {str(e)}")
            time.sleep(3)
            return False    

    def clear_browsing_data(self):
        """Tarama verilerini siler"""
        try:
            # CDP komutları ile tarayıcı önbelleği, çerezler ve tarayıcı geçmişini temizler
            self.driver.execute_cdp_cmd("Network.clearBrowserCache", {})
            self.driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
            self.driver.execute_cdp_cmd("Storage.clearDataForOrigin", {
                "origin": "*",
                "storageTypes": "all"
            })
            logger.info("cache, cookies and browser history cleared")
            
            # Çerezlerin temizlendiğini doğrula
            cookies = self.driver.execute_cdp_cmd("Network.getAllCookies", {})
            if cookies['cookies']:
                logger.warning("cookies could not be cleared")
            else:
                logger.info("cookies successfully cleared")
                
            return True

        except Exception as e:
            logger.error(f"browsing data clear error: {str(e)}")
            return False

    def close(self):
        """Oturumu kapatır ve tarayıcıyı temiz şekilde sonlandırır"""
        try:
            if hasattr(self, 'driver'):
                logger.info(f"logout started - {self.username}")
                
                # Önce oturumu kapat
                logout_success = self.log_out()
                time.sleep(3)
                
                # Tarayıcıyı kapat
                browser_success = self.quit()
                
                if logout_success and browser_success:
                    logger.info("session and browser closed successfully")
                    return True
                elif not logout_success and browser_success:
                    logger.warning("logout failed but browser closed")
                    return True
                else:
                    logger.error("session and browser close failed")
                    return False
                    
        except Exception as e:
            logger.error(f"close operation error: {str(e)}")
            return False

    def quit(self):
        """Tarayıcıyı güvenli şekilde kapatır"""
        try:
            if hasattr(self, 'driver'):
                self.driver.quit()
                logger.info("browser closed successfully")
                return True
        except Exception as e:
            logger.error(f"browser close error: {str(e)}")
            return False

    def log_out(self):
        """Profile tıklayıp Log Out yapar"""
        try:
            # First check if the driver session is valid
            if not self.is_driver_valid():
                logger.warning("WebDriver session is invalid")
                return False
                
            logger.info("logging out...")
            print("[1/4] redirecting to home page...")
            self.driver.get("https://x.com/home")
            time.sleep(3)

            print("[2/4] opening profile menu...")
            # Profil butonu tıklama
            profile_clicked = False
            for selector in self.profile_selectors['xpath'] + self.profile_selectors['css']:
                try:
                    button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH if selector.startswith('//') else By.CSS_SELECTOR, selector))
                    )
                    self.driver.execute_script("arguments[0].click();", button)
                    profile_clicked = True
                    break
                except:
                    continue

            if not profile_clicked:
                print("profile button not found")
                return False

            time.sleep(3)
            print("[3/4] logout is being done...")
            # Logout butonu tıklama
            logout_clicked = False
            for selector in self.logout_selectors['xpath'] + self.logout_selectors['css']:
                try:
                    button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH if selector.startswith('//') else By.CSS_SELECTOR, selector))
                    )
                    self.driver.execute_script("arguments[0].click();", button)
                    logout_clicked = True
                    break
                except:
                    continue

            if not logout_clicked:
                print("logout button not found")
                return False

            time.sleep(3)
            print("[4/4] logout is being confirmed...")

            # Onay butonu tıklama
            confirm_clicked = False
            for selector in self.confirm_logout_selectors['xpath'] + self.confirm_logout_selectors['css']:
                try:
                    button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH if selector.startswith('//') else By.CSS_SELECTOR, selector))
                    )
                    self.driver.execute_script("arguments[0].click();", button)
                    confirm_clicked = True
                    break
                except:
                    continue

            if not confirm_clicked:
                print("confirm logout button not found")
                return False

            # Çıkış kontrolü
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda x: "login" in x.current_url or "i/flow/login" in x.current_url
                )
                print("logout successful")
                return True
            except:
                print("logout successful but not verified")
                return True  # Yine de True döndür çükünü işlem muhtemelen başarılı

        except Exception as e:
            print(f"logout error: {str(e)}")
            return False

    def is_driver_valid(self):
        """WebDriver oturumunun geçerli olup olmadığını kontrol eder."""
        try:
            self.driver.current_url  # Oturumun geçerli olup olmadığını test et
            return True
        except Exception:
            return False

    # Güncellenmiş seçiciler
    profile_selectors = {
        'xpath': [
            '//div[@data-testid="SideNav_AccountSwitcher_Button"]',
            '//div[@aria-label="Account menu"]',
            '//div[@aria-label="Hesap menüsü"]',  # Türkçe
            '//div[contains(@aria-label, "Account") and contains(@aria-label, "menu")]'
        ],
        'css': [
            '[data-testid="SideNav_AccountSwitcher_Button"]',
            '[aria-label="Account menu"]',
            '[aria-label="Hesap menüsü"]'  # Türkçe
        ]
    }

    logout_selectors = {
        'xpath': [
            '//a[@data-testid="AccountSwitcher_Logout_Button"]',
            '//span[text()="Log out"]',
            '//span[text()="Çıkış yap"]',  # Türkçe
            '//span[contains(text(), "Log")]',
            '//span[contains(text(), "Çıkış")]'  # Türkçe
        ],
        'css': [
            '[data-testid="AccountSwitcher_Logout_Button"]',
            '[role="menuitem"][data-testid="AccountSwitcher_Logout_Button"]'
        ]
    }

    confirm_logout_selectors = {
        'xpath': [
            '//div[@data-testid="confirmationSheetConfirm"]',
            '//span[text()="Log out"]',
            '//span[text()="Çıkış yap"]',  # Türkçe
            '//div[@role="button"]//span[contains(text(), "Log")]',
            '//div[@role="button"]//span[contains(text(), "Çıkış")]'  # Türkçe
        ],
        'css': [
            '[data-testid="confirmationSheetConfirm"]',
            'div[role="dialog"] button[role="button"]:last-child'
        ]
    }

    # XPath tanımlamaları
    username_xpath = '/html/body/div/div/div/div[1]/div/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[2]/div/div/div/div[4]/label/div/div[2]/div/input'
    button_xpath = '/html/body/div/div/div/div[1]/div/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[2]/div/div/div/button[2]/div'
    password_xpath = '//*[@id="layers"]/div/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[2]/div[1]/div/div/div[3]/div/label/div/div[2]/div[1]/input'
    login_button_xpath = '//*[@id="layers"]/div/div/div/div/div/div/div[2]/div[2]/div/div/div[2]/div[2]/div[2]/div/div/div/div/button/div/span/span'
    test_tweet = 'https://x.com/zoltanszabo422/status/1596340888925802496'
    like_button_xpath = '//*[@id="id__h5h1jnfwj6u"]/div[3]/button/div/div[2]/span/span'
    cookie_button_xpath = '/html/body/div[1]/div/div/div[1]/div[1]/div/div/div/div/div[2]/button[1]/div'
    notification_button_xpath = '//*[@id="layers"]/div[2]/div/div/div/div/div/div[2]/div[2]/div/div[2]/div/div[2]/div[2]/div[1]/div/span/span'
    twitter_notifications_tab_xpath = "//a[@href='/notifications']"
    reetweet_button_xpath = '//*[@id="id__h5h1jnfwj6u"]/div[2]/button/div/div[1]/svg'
    reetweet_confirm_button_xpath = '/html/body/div[1]/div/div/div[1]/div[2]/div/div/div/div[2]/div/div[3]/div/div/div/div/div[2]/div/span'
    comment_button_xpath = '//*[@id="id__h5h1jnfwj6u"]/div[3]/button/div/div[2]/span/span'
    textbox_xpath = '//*[@id="layers"]/div[2]/div/div/div/div/div/div[2]/div[2]/div/div/div/div[3]/div[2]/div[2]/div/div/div/div/div[2]/div[1]/div/div/div/div/div/div/div/div/div/div/label/div[1]/div/div/div/div/div/div[2]/div/div/div/div'
    follow_button_xpath = "/html/body/div[1]/div/div/div[2]/main/div/div/div/div/div/div[3]/div/div/div/div/div[1]/div[2]/div[3]/div[1]/div"
    profile_xpath = '/html/body/div[1]/div/div/div[2]/header/div/div/div/div[3]/div[2]/button/div/div/div[2]/div/div[2]/div/div/div[4]/div'
    logout_xpath = '/html/body/div[1]/div/div/div[1]/div[2]/div/div/div[2]/div/div[2]/div/div/div/div/div/a[2]/div[1]/div'
    confirm_logout_xpath = '/html/body/div[1]/div/div/div[1]/div[2]/div/div/div/div/div/div[2]/div[2]/div[2]/button[1]/div/span/span'
    unfollow_nbr = 0

    def find_and_click(self, xpath, timeout=15, retries=5):
        """XPath ile element bulup tıklar"""
        for attempt in range(retries):
            try:
                element = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                element.click()
                logger.debug(f"element başarıyla tıklandı: {xpath}")
                return True
            except Exception as e:
                if attempt == retries - 1:
                    logger.error(f"element tıklanamadı: {xpath}")
                    logger.error(f"Hata detayı: {str(e)}")
                    return False
                time.sleep(random.randint(1, 3))

    def find_and_send_keys(self, xpath, keys, timeout=10):
        """XPath ile element bulup metin gönderir"""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            element.clear()
            element.send_keys(keys)
            logger.debug(f"metin başarıyla gönderildi: {xpath}")
            return True
        except Exception as e:
            logger.error(f"element bulunamadı veya metin gönderilemedi: {xpath}")
            logger.error(f"Hata detayı: {str(e)}")
            return False

    def click_notifications_tab(self):
        """Bildirimler sekmesine tıklar ve kontrol eder"""
        try:
            wait = WebDriverWait(self.driver, 15)
            
            # Bildirimler sekmesi için çoklu seçici
            selectors = [
                "//a[@href='/notifications']",
                "//a[@data-testid='AppTabBar_Notifications_Link']",
                "//span[text()='Notifications']",
                "//span[text()='Bildirimler']"  # Türkçe desteği
            ]
            
            clicked = False
            for selector in selectors:
                try:
                    notifications_tab = wait.until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    self.driver.execute_script("arguments[0].click();", notifications_tab)
                    clicked = True
                    logger.debug(f"notifications tab done")
                    break
                except:
                    continue
                    
            if not clicked:
                logger.error("notifications tab not found")
                return False
                
            time.sleep(3)
            
            # url ve sayfa yükleme kontrolü
            if "notifications" in self.driver.current_url:
                if self.wait_for_page_load(10):
                    logger.info("notifications page opened successfully")
                    return True
                    
            logger.error("notifications page open failed")
            return False
            
        except Exception as e:
            logger.error(f"notifications tab click error: {str(e)}")
            return False

    def show_time():
        """Show the starting time"""
        tr_timezone = timezone(timedelta(hours=3))
        current_time = datetime.now(tr_timezone)
        
        logger.info("" + "="*50)
        logger.info(f"Tarih ve saat (Türkiye): {current_time.strftime('%d-%m-%Y %H:%M:%S')}")
        logger.info("="*50 + "")

def accept_cookie(self):
    """Çerez kabul işlemi - sadece bir kez çalışır"""
    if self.cookie_accepted:
        logger.debug("cookies already accepted")
        return True
        
    try:
        cookie_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="cookie-consent-button"]'))
        )
        cookie_button.click()
        self.cookie_accepted = True
        logger.info("cookies accepted")
        return True
    except TimeoutException:
        self.cookie_accepted = True
        logger.debug("cookie done")
        return True
    except Exception as e:
        logger.error(f"cookie accept error: {str(e)}")
        return False

def accept_notification(self):
    """Bildirim izni işlemi - sadece bir kez çalışır"""
    if self.notification_accepted:
        logger.debug("notifications already accepted")
        return True
        
    try:
        notification_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="notification-permission-button"]'))
        )
        notification_button.click()
        self.notification_accepted = True
        logger.info("notifications accepted")
        return True
    except TimeoutException:
        self.notification_accepted = True
        logger.debug("notifications done")
        return True
    except Exception as e:
        logger.error(f"notifications accept error: {str(e)}")
        return False

def perform_tweet_interactions(S, tweet_url, comment_text, rate_limiter: TwitterRateLimiter):
    """
    Tweet ile etkileşim gerçekleştirir (beğeni, retweet, yorum)
    
    Args:
        S: Scraper instance
        tweet_url: Tweet url'i
        comment_text: Yorum metni (opsiyonel)
        rate_limiter: Rate limiter instance
    
    Returns:
        tuple: (like_success, retweet_success, comment_success)
    """
    try:
        logger.info("="*50)
        logger.debug(f"processing tweet: {tweet_url}")

        # Like işlemi için rate limit kontrolü
        if check_rate_limit(rate_limiter.username, "like"):
            logger.warning("like rate limit active, skipping like")
            like_success = False
        else:
            like_success = like_a_tweet(S, tweet_url, rate_limiter)
            if not like_success:
                logger.error(f"failed to like tweet: {tweet_url}")

        # Retweet işlemi için rate limit kontrolü
        if check_rate_limit(rate_limiter.username, "retweet"):
            logger.warning("retweet rate limit active, skipping retweet")
            retweet_success = False
        else:
            retweet_success = retweet_a_tweet(S, tweet_url, rate_limiter)
            if not retweet_success:
                logger.error(f"failed to retweet: {tweet_url}")

        # Yorum işlemi için rate limit kontrolü
        comment_success = False
        if comment_text:
            if check_rate_limit(rate_limiter.username, "comment"):
                logger.warning("comment rate limit active, skipping comment")
            else:
                comment_success = comment_a_tweet(S, tweet_url, comment_text, rate_limiter)
                if not comment_success:
                    logger.error(f"failed to add comment: {tweet_url}")
                else:
                    logger.info(f"comment added successfully: {comment_text[:50]}...")

        # Sonuçları logla
        logger.info("="*50)
        logger.info("interaction Results:")
        logger.info(f"like: {'✓' if like_success else '✗'}")
        logger.info(f"retweet: {'✓' if retweet_success else '✗'}")
        logger.info(f"comment: {'✓' if comment_success else '✗'}")
        logger.info("="*50)

        return like_success, retweet_success, comment_success

    except Exception as e:
        logger.error("="*50)
        logger.error(f"tweet interaction error:")
        logger.error(f"user: {rate_limiter.username}")
        logger.error(f"uRL: {tweet_url}")
        logger.error(f"Error: {str(e)}")
        logger.error("="*50)
        return False, False, False

def get_comment_template(news_title, news_content=""):
    """Haber içeriğine göre uygun İngilizce yorum şablonu seçer"""
    
    try:
        # Kategoriler ve anahtar kelimeler
        categories = {
            'positive': ['success', 'breakthrough', 'achievement', 'growth', 'improvement', 'record', 'win', 'rise'],
            'negative': ['decline', 'fall', 'crisis', 'problem', 'issue', 'crash', 'failed', 'loss'],
            'technology': ['technology', 'ai', 'digital', 'software', 'app', 'device', 'tech', 'innovation'],
            'business': ['market', 'stock', 'company', 'business', 'revenue', 'profit', 'investment'],
            'general': []
        }

        # İngilizce yorum şablonları
        templates = {
            'positive': [
                "This comment nails it perfectly 👏",
                "Couldn't agree more with this comment 🎉",
                "Someone gets it right:",
                "Best take on this news:",
                "Love this perspective 💯"
            ],
            'negative': [
                "This comment sums it up well:",
                "Someone highlighting the key issue:",
                "Important observation in the comments:",
                "This perspective needs attention:",
                "Thought-provoking comment here:"
            ],
            'technology': [
                "Tech insight worth sharing:",
                "Interesting tech perspective 🚀",
                "Smart take on this development:",
                "This view on tech evolution:",
                "Valid point about innovation:"
            ],
            'business': [
                "Sharp market analysis here:",
                "Interesting market perspective 📈",
                "Smart business observation:",
                "This insight on market trends:",
                "Spot-on analysis:"
            ],
            'general': [
                "Worth sharing this comment 👌",
                "Interesting perspective:",
                "Totally agree with this:",
                "Best comment on this:",
                "This one makes sense:"
            ]
        }

        # İçerikten kategori belirle
        title_lower = news_title.lower()
        content_lower = news_content.lower()
        news_category = 'general'
        
        for category, keywords in categories.items():
            if any(keyword in title_lower or keyword in content_lower for keyword in keywords):
                news_category = category
                logger.debug(f"news category was determined: {category}")
                break

        selected_template = templates[news_category][randint(0, len(templates[news_category])-1)]
        logger.debug(f"selected template: {selected_template}")
        return selected_template

    except Exception as e:
        logger.error(f"comment template selection error: {str(e)}")
        return templates['general'][0]  # Default template

def make_a_tweet(S, text):
    """Tweet paylaşma fonksiyonu - ActionChains ile emoji desteği"""
    try:
        logger.info(f"initiating tweet sharing - {S.username}")
        logger.debug(f"tweet text: {text[:50]}...")

        # Tweet compose sayfasına git
        S.driver.get("https://x.com/compose/tweet")
        time.sleep(5)
        
        # Tweet textbox'ını bul
        textbox = WebDriverWait(S.driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'))
        )
        
        # ActionChains oluştur
        actions = ActionChains(S.driver)
        actions.move_to_element(textbox)
        actions.click()
        actions.pause(1)
        
        # Metni temizle
        textbox.clear()
        
        # Metni karakter karakter yaz
        for char in text:
            actions.send_keys(char)
            actions.pause(0.1)
        
        # Aksiyonları gerçekleştir
        actions.perform()
        logger.debug("tweet text entered")
        time.sleep(3)
        
        # Tweet butonunu bul ve tıkla
        tweet_button = WebDriverWait(S.driver, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="tweetButton"]'))
        )
        
        # Butonu görünür yap ve tıkla
        S.driver.execute_script("arguments[0].scrollIntoView();", tweet_button)
        time.sleep(3)
        tweet_button.click()
        
        # Tweet paylaşımının başarılı olduğunu kontrol et
        time.sleep(5)
        
        # Hata mesajı kontrolü
        try:
            error_message = S.driver.find_element(By.CSS_SELECTOR, '[data-testid="error-message"]')
            if error_message.is_displayed():
                logger.error(f"tweet sharing fails: {error_message.text}")
                return False
        except:
            return True
            
    except Exception as e:
        logger.error(f"tweet sharing error - {S.username}, error: {str(e)}")
        return False

def perform_random_tweet_rt(S, rate_limiter: TwitterRateLimiter, random_action, random_tweet_nb, random_retweet_nb, sentence_to_tweet):
    """Rastgele tweet ve RT işlemleri gerçekleştirir"""
    try:
        current_time = datetime.now(timezone(timedelta(hours=3))).strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"random tweet/rt actions started")
        logger.info(f"{current_time}")
        logger.info(f"{S.username}")

        tweet_success = False
        
        # Tweet paylaşımları (Haber Tweet'leri)
        if random_action and random_tweet_nb > 0:
            tweet_count = randint(1, random_tweet_nb)
            logger.info(f"target tweet count: {tweet_count}")
            
            for i in range(tweet_count):
                info, info_link = get_news()
                if info and info_link:
                    tweet_text = f"{info} {info_link}"
                    success = make_a_tweet(S, tweet_text)
                    tweet_success = success
                    if success:
                        logger.success(f"tweet shared ({i+1}/{tweet_count})")
                    time.sleep(randint(5, 10))

        # Kısa tweet paylaşımı
        if (not tweet_success or random_tweet_nb == 0) and random_retweet_nb > 0:
            logger.info("launching short tweet sharing")
            
            if sentence_to_tweet and len(sentence_to_tweet) > 0:
                tweet_text = sentence_to_tweet[randint(0, len(sentence_to_tweet) - 1)]
                success = make_a_tweet(S, tweet_text)
                if not success:
                    logger.error("short tweet sharing fails")
            else:
                logger.warning("tweet list empty or invalid")
            
            time.sleep(randint(5, 10))


        # Retweet işlemleri
        if random_retweet_nb > 0:
            logger.info("rt operations are being initiated")
            rt_url = search_tweet_for_better_rt(S)
            rt_count = 0
            
            for rt_link in rt_url:
                if rt_link and rt_link.strip():
                    try:
                        if not rate_limiter.can_perform_action("like"):
                            wait_time = rate_limiter.action_limits['like']['window']
                            logger.info(f"like limit exceeded, waiting {wait_time} seconds")
                            time.sleep(wait_time)
                        
                        like_success = like_a_tweet(S, rt_link, rate_limiter)
                        
                        if like_success:
                            if not rate_limiter.can_perform_action("retweet"):
                                wait_time = rate_limiter.action_limits['retweet']['window']
                                logger.info(f"retweet limit exceeded, waiting {wait_time} seconds")
                                time.sleep(wait_time)
                            
                            retweet_result = retweet_a_tweet(S, rt_link, rate_limiter)
                            if retweet_result:
                                rt_count += 1
                                rate_limiter.log_action("retweet")
                                logger.success(f"tweet was rt ({rt_count}): {rt_link}")
                        
                        time.sleep(randint(5, 10))
                        
                    except Exception as e:
                        logger.error(f"rt operation failed: {str(e)}")
                        continue
            
            logger.info(f"total {rt_count} tweet were rt")
        
    except Exception as e:
        logger.error(f"random tweet/rt actions failed: {str(e)}")
    finally:
        time.sleep(randint(5, 10))

def get_news():
    """RSS feedlerinden haber alır ve işler"""
    shared_links = set()
    
    # Kullanılmış linkleri oku
    try:
        with open("shared_links.txt", "r", encoding='utf-8') as f:
            shared_links = set(f.read().splitlines())
        logger.debug(f"shared links loaded - total: {len(shared_links)}")
    except FileNotFoundError:
        logger.info("shared_links.txt file not found, new file will be created")
    except Exception as e:
        logger.error(f"shared_links.txt read error: {str(e)}")
    
    try:
        with open("configuration.yml", "r", encoding='utf-8') as file:
            data = yaml.safe_load(file)
            url_list = data["flux_rss"]
            sentence_to_tweet = data["sentence_to_tweet"]
            logger.debug(f"configuration loaded - RSS feed count: {len(url_list)}")
        
        # Kullanılmamış RSS feedlerini bul
        available_feeds = [l for l in url_list if l not in shared_links]
        if not available_feeds:
            logger.info("all RSS feeds are used, resetting list")
            available_feeds = url_list
            shared_links.clear()
        
        l = available_feeds[randint(0, len(available_feeds) - 1)]
        logger.debug(f"selected RSS feed: {l}")
        news_feed = feedparser.parse(l)

        news_title = []
        news_link = []
        
        # Kullanılmamış haberleri filtrele
        for entry in news_feed.entries:
            if entry.link not in shared_links:
                news_title.append(entry.title)
                news_link.append(entry.link)
                break  # İlk uygun haberi al
        
        if not news_title:
            logger.warning(f"this feed has no new news: {l}")
            return get_news()  # Recursive tekrar dene
        
        # Yeni haber seç
        selected_news = (news_title[0], news_link[0])
        
        # Kullanılan linki dosyaya ekle
        shared_links.add(selected_news[1])
        try:
            with open("shared_links.txt", "w", encoding='utf-8') as f:
                f.write("\n".join(shared_links) + "\n")
            logger.debug(f"new link saved: {selected_news[1]}")
        except Exception as e:
            logger.error(f"link save error: {str(e)}")
        
        logger.info(f"news selected - Title: {selected_news[0][:50]}...")
        return selected_news
        
    except Exception as e:
        logger.error(f"RSS reading error: {str(e)}")
        if not sentence_to_tweet:
            logger.error("tweet template list is empty or invalid")
            return ("", "")
        random_tweet = sentence_to_tweet[randint(0, len(sentence_to_tweet) - 1)]
        logger.info(f"alternative tweet used: {random_tweet[:50]}...")
        return (random_tweet, "")

def follow_an_account(S, account_name, max_retries, username, password, rate_limiter: TwitterRateLimiter):
    """
    Belirtilen hesabı takip eden fonksiyon.
    
    Args:
        S: Selenium oturumu
        account_name: Takip edilecek hesap adı
        max_retries: Maksimum deneme sayısı
        username: Giriş yapan kullanıcı adı
        password: Giriş yapan kullanıcı parolası
        rate_limiter: Rate limiter instance
    """
    current_time = datetime.now(tr_timezone)
    retry_count = 0
    
    # Rate limit kontrolü
    if not rate_limiter.can_perform_action("follow"):
        logger.warning("" + "="*50)
        logger.warning(f"[rate limit] {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.warning(f"[rate limit] follow limit exceeded! ({rate_limiter.limits['follow']['hourly']} transactions/hour, {rate_limiter.limits['follow']['daily']} transactions/day)")
        logger.warning(f"[rate limit] {rate_limiter.username}")
        logger.warning("="*50)
        return False

    try:
        logger.info("" + "="*50)
        logger.info(f"{current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"follow processing: {account_name}")
        logger.info("="*50)
        
        while retry_count < max_retries:
            try:
                # Kullanıcı adı uzunluk kontrolü
                if len(account_name) > 15:
                    logger.warning(f"username too long, account is skipped: {account_name}")
                    time.sleep(randint(5, 10))
                    return False  # Uzun isimler için False dön

                # Browser durumunu kontrol et
                try:
                    S.driver.current_url
                except:
                    logger.warning("browser session refreshes...")
                    if not try_login_again(S, username, password):
                        logger.error("failed to refresh browser session")
                        return False
                    time.sleep(5)

                # Hesap sayfasına git
                S.driver.get("https://x.com/" + account_name)
                element = WebDriverWait(S.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="placementTracking"]'))
                )
                follow_button = S.driver.find_element(By.CSS_SELECTOR, '[data-testid="placementTracking"]')

                # Farklı dillerdeki "takip et" butonları için kontrol
                follow_texts = [
                    "follow", "suivre", "seguir", "フォローする", "팔로우", "следить", "folgen", 
                    "segui", "seguir+", "siga", "sledovať", "takip et", "folowă", "अनुसरण करें", 
                    "ikuti", "متابعة", "关注", "關注", "следите", "śledź", "seguí", "तलाशें", 
                    "siguir", "フォロー", "segui-la", "sígueme", "следи за", "siga-me", "följa", 
                    "seuraa", "følge", "segura", "跟隨"
                ]

                # Zaten takip ediliyor mu kontrolü
                if follow_button.text.lower() not in follow_texts:
                    logger.debug(f"{account_name} account is already being followed")
                    time.sleep(randint(5, 10))
                    return False  # Zaten takip ediliyorsa False dön

                # Takip etme işlemi
                follow_button.click()
                time.sleep(randint(5, 10))
                rate_limiter.log_action("follow")  # Sadece yeni takipte logla
                
                logger.success(f"{account_name} account is followed")
                
                wait_time = rate_limiter._get_random_interval("follow")
                logger.info(f"after the follow-up, {wait_time} seconds will be waited")
                time.sleep(wait_time)
                return True

            except Exception as e:
                retry_count += 1
                logger.error(f"attempt {retry_count}/{max_retries}")
                
                # Oturum düşmesi durumu kontrolü
                if "Account got logged out" in str(e):
                    logger.warning(f"session down, trying to log in again...")
                    logger.info(f"{username}")
                    if username and password:
                        if try_login_again(S, username, password):
                            continue
                    else:
                        logger.error("user information missing, unable to log in again")
                        return False
                
                time.sleep(randint(5, 10))  # Hata sonrası daha uzun bekleme
                
                if retry_count == max_retries:
                    logger.error(f"maximum number of attempts reached - {account_name}")
                    return False

        return False
        
    except Exception as e:
        logger.error("" + "="*50)
        logger.error(f"following process failed")
        logger.error(f"details: {str(e)}")
        logger.error("="*50)
        return False

def like_a_tweet(selenium_session, url: str, rate_limiter: TwitterRateLimiter) -> bool:
    current_time = datetime.now(tr_timezone)
    
    if not url or not url.startswith('https://x.com/'):
        logger.error(f"invalid tweet url: {url}")
        return False

    if not rate_limiter.can_perform_action("like"):
        logger.warning(f"like limit exceeded")
        logger.debug(f"like limit information: {rate_limiter.limits['like']['hourly']}/hour, {rate_limiter.limits['like']['daily']}/day")
        return False
        
    try:
        logger.debug(f"process url: {url}")
        
        # Sayfa yükleme ve element kontrolü
        selenium_session.driver.get(url)
        WebDriverWait(selenium_session.driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweet"]'))
        )
        time.sleep(randint(2, 4))

        # Zaten beğenilmiş mi kontrolü
        try:
            unlike_button = WebDriverWait(selenium_session.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="unlike"]'))
            )
            logger.info(f"tweet already liked")
            return True
        except:
            # Beğenme işlemi
            try:
                like_button = WebDriverWait(selenium_session.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="like"]'))
                )
                selenium_session.driver.execute_script("arguments[0].scrollIntoView(true);", like_button)
                time.sleep(3)
                selenium_session.driver.execute_script("arguments[0].click();", like_button)
                
                # Başarı kontrolü
                WebDriverWait(selenium_session.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="unlike"]'))
                )
                
                rate_limiter.log_action("like")
                
                wait_time = rate_limiter._get_random_interval("like")
                logger.debug(f"wait time: {wait_time} seconds")
                time.sleep(wait_time)
                return True

            except Exception as e:
                logger.error(f"tweet like failed, error: {str(e)}")
                return False

    except Exception as e:
        logger.error(f"tweet like process failed, error: {str(e)}")
        return False

def retweet_a_tweet(selenium_session, url: str, rate_limiter: TwitterRateLimiter) -> bool:
    current_time = datetime.now(tr_timezone)

    if not rate_limiter.can_perform_action("retweet"):
        logger.warning(f"retweet limit exceeded")
        logger.debug(f"retweet limit information: {rate_limiter.limits['retweet']['hourly']}/hour, {rate_limiter.limits['retweet']['daily']}/day")
        return False

    try:
        selenium_session.driver.implicitly_wait(15)
        selenium_session.driver.get(url)
        time.sleep(0.001)
        
        element = WebDriverWait(selenium_session.driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="retweet"]')))
        retweet_button = selenium_session.driver.find_element(By.CSS_SELECTOR, '[data-testid="retweet"]')
        selenium_session.driver.execute_script("arguments[0].click();", retweet_button)

        try:
            element = WebDriverWait(selenium_session.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="retweetConfirm"]')))
            confirm_button = selenium_session.driver.find_element(By.CSS_SELECTOR, '[data-testid="retweetConfirm"]')
            selenium_session.driver.execute_script("arguments[0].click();", confirm_button)
            
            rate_limiter.log_action("retweet")
            
            wait_time = rate_limiter._get_random_interval("retweet")
            logger.debug(f"wait time: {wait_time} seconds")
            time.sleep(wait_time)
            return True
            
        except:
            logger.warning(f"retweet confirmation button not found")
            time.sleep(3)    
            return False
            
    except Exception as e:
        if "net::ERR_NAME_NOT_RESOLVED" in str(e):
            logger.error(f"network error, waiting 3 minutes...")
            time.sleep(180)
        else:
            logger.error(f"retweet error")
        return False

def comment_a_tweet(selenium_session, url: str, text: str, rate_limiter: TwitterRateLimiter) -> bool:
    current_time = datetime.now(tr_timezone)

    if not rate_limiter.can_perform_action("comment"):
        wait_time = rate_limiter.get_wait_time("comment")
        logger.warning(f"Yorum limiti aşıldı - {rate_limiter.username}")
        logger.debug(f"Limit bilgisi: {rate_limiter.limits['comment']['hourly']}/saat, {rate_limiter.limits['comment']['daily']}/gün")
        logger.info(f"Bekleme süresi: {wait_time} saniye")
        time.sleep(wait_time)
        return False

    try:
        logger.info(f"Yorum işlemi başlatılıyor - {rate_limiter.username}")
        logger.debug(f"İşlenecek URL: {url}")
        logger.debug(f"Yorum metni: {text[:50]}...")

        # Sayfayı yükle ve bekle
        selenium_session.driver.get(url)
        time.sleep(3)  # Minimum 3 saniye bekle
        
        # Tweet bölümünü bul ve bekle
        wait = WebDriverWait(selenium_session.driver, 15)
        try:
            tweet_container = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
            )
        except TimeoutException:
            logger.error("Tweet container bulunamadı")
            return False

        # Reply butonunu bul
        try:
            comment_button = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="reply"]'))
            )
        except TimeoutException:
            logger.error("Reply butonu bulunamadı")
            return False

        # JavaScript ile tıklama
        try:
            selenium_session.driver.execute_script("arguments[0].scrollIntoView(true);", comment_button)
            time.sleep(1)
            selenium_session.driver.execute_script("arguments[0].click();", comment_button)
            logger.debug("Reply butonu tıklandı")
        except Exception as e:
            logger.error(f"Reply butonuna tıklama hatası: {str(e)}")
            return False

        time.sleep(3)

        # Yorum kutusunu bul ve metni yaz
        try:
            textbox = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'))
            )
            selenium_session.driver.execute_script("arguments[0].scrollIntoView(true);", textbox)
            time.sleep(1)
            
            # Metni harf harf yaz
            for t in text:
                textbox.send_keys(t)
                time.sleep(0.1)  # Her harf arasında küçük gecikme
            
            textbox.send_keys(" ")  # Boşluk ekle
            logger.debug("Yorum metni girildi")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Metin girişi hatası: {str(e)}")
            return False

        # Tweet butonunu bul ve tıkla
        try:
            tweet_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="tweetButton"]'))
            )
            selenium_session.driver.execute_script("arguments[0].scrollIntoView(true);", tweet_button)
            time.sleep(1)
            selenium_session.driver.execute_script("arguments[0].click();", tweet_button)
            logger.debug("Tweet butonu tıklandı")
        except Exception as e:
            logger.error(f"Tweet butonu hatası: {str(e)}")
            return False

        # İşlem sonrası bekle ve kaydet
        time.sleep(5)
        rate_limiter.log_action("comment")
        logger.success(f"Yorum başarıyla eklendi - {rate_limiter.username}")
        
        # Rate limiter aralığı kadar bekle
        wait_time = rate_limiter._get_random_interval("comment")
        logger.debug(f"Bekleme süresi: {wait_time} saniye")
        time.sleep(wait_time)
        
        return True

    except Exception as e:
        logger.error(f"Yorum ekleme hatası - {rate_limiter.username}, Hata: {str(e)}")
        return False

def login(S, _username, _password):
    try:
        S.driver.get("https://x.com/i/flow/login")
        S.driver.switch_to.window(S.driver.current_window_handle)
        logger.info(f"initializing login - {_username}")
        if not S.wait_for_page_load():
            logger.error("Page failed to load")
            raise Exception("Page load timeout")

        logger.debug("Attempting to find username field")
        element = WebDriverWait(S.driver, 60).until(
            EC.element_to_be_clickable((By.XPATH, S.username_xpath)))
        username = S.driver.find_element(By.XPATH, S.username_xpath)
        username.send_keys(_username)
        logger.debug("username entered")

        logger.debug("Attempting to click Next button")
        element = WebDriverWait(S.driver, 60).until(
            EC.element_to_be_clickable((By.XPATH, S.button_xpath)))
        button = S.driver.find_element(By.XPATH, S.button_xpath)
        button.click()
        logger.debug("Next button clicked")

        logger.debug("Attempting to find password field")
        element = WebDriverWait(S.driver, 60).until(
            EC.element_to_be_clickable((By.XPATH, S.password_xpath)))
        password = S.driver.find_element(By.XPATH, S.password_xpath)
        password.send_keys(_password)
        logger.debug("password entered")

        logger.debug("Attempting to click login button")
        element = WebDriverWait(S.driver, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="LoginForm_Login_Button"]')))
        login_button = S.driver.find_element(By.CSS_SELECTOR, '[data-testid="LoginForm_Login_Button"]')
        login_button.click()
        logger.debug("login button clicked")

        logger.debug("Checking login status")
        for attempt in range(3):
            time.sleep(5)
            if check_login_good(S):
                logger.info(f"login successful - {_username}")
                return True

        logger.error(f"login failed - incorrect username or password: {_username}")
        return False

    except Exception as e:
        logger.error(f"login error - {_username}: {str(e)}")
        time.sleep(5)
        if try_login_again(S, _username, _password):
            return True
        logger.error(f"login failed - {_username}")
        return False

def try_login_again(S, current_user, current_pass):
    """Yeniden giriş yapmayı dener"""
    logger.info(f"re-login attempt started - {current_user}")
    
    if not login(S, current_user, current_pass):
        logger.warning(f"first login attempt failed: {current_user}")
        time.sleep(randint(60, 120))
        
        logger.info(f"second login attempt: {current_user}")
        if not login(S, current_user, current_pass):
            logger.error(f"second login attempt failed: {current_user}")
            return False
    
    logger.success(f"re-login successful: {current_user} - {datetime.now(tr_timezone).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Cookie ve bildirim işlemleri
    logger.debug("cookies are accepted...")
    accept_cookie(S)
    time.sleep(S.wait_time)    
    
    logger.debug("notification permission granted...")
    accept_notification(S)
    time.sleep(S.wait_time)
    
    logger.debug("cookie consent granted...")
    accept_cookie(S)
    time.sleep(S.wait_time)
    
    return True

def check_login_good(selenium_session):
    """Oturum durumunu kontrol eder"""
    try:
        # Sayfa yenilemek yerine mevcut sayfada belirli bir elemanın varlığını kontrol ediyoruz
        WebDriverWait(selenium_session.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="AppTabBar_Notifications_Link"]')))
        logger.info(f"session status check: active - {datetime.now(tr_timezone).strftime('%Y-%m-%d %H:%M:%S')}")
        return True
    except TimeoutException:
        logger.error("session status check failed: page load timeout")
        return False
    except Exception as e:
        logger.error(f"session status check failed: {str(e)}")
        return False

def check_if_good_account_login(S, account):
    """Check if the session is active on the correct account"""
    try:
        S.driver.get("https://x.com/" + account)
        element = WebDriverWait(S.driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,'[data-testid="userActions"]')))
        u = S.driver.find_element(By.CSS_SELECTOR,'[data-testid="userActions"]')
        logger.warning(f"wrong account - {account} - {datetime.now(tr_timezone).strftime('%Y-%m-%d %H:%M:%S')}")
        return False
    except TimeoutException:
        logger.debug(f"correct account check successful (timeout): {account}")
        return True
    except NoSuchElementException:
        logger.debug(f"correct account check successful (element not found): {account}")
        return True
    except Exception as e:
        logger.error(f"account check error - {account}: {str(e)}")
        return True

def is_account_log_out(S):
    """Oturumun aktif olup olmadığını kontrol eder (maksimum 2 deneme)"""
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            logger.debug(f"checking session status, attempt {attempt+1}...")
            S.driver.implicitly_wait(15)
            S.driver.get("https://x.com/compose/post")
            time.sleep(5)  # Sayfanın yüklenmesi için bekleme

            # Sayfayı yenile ve bekle
            S.driver.refresh()
            time.sleep(5)

            # Tweet alanını kontrol et
            element = WebDriverWait(S.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'))
            )
            logger.success(f"session active - element found - {datetime.now(tr_timezone).strftime('%Y-%m-%d %H:%M:%S')}")
            return True

        except TimeoutException:
            logger.warning(f"tweet textarea not found on attempt {attempt+1}")
            if attempt < max_attempts - 1:
                logger.debug("Refreshing page and retrying...")
                S.driver.refresh()
                time.sleep(5)
            else:
                logger.warning(f"session logout detected - tweet textarea still missing after {max_attempts} attempts - {datetime.now(tr_timezone).strftime('%Y-%m-%d %H:%M:%S')}")
                # Ek kontrol: Giriş ekranı var mı?
                try:
                    login_prompt = S.driver.find_element(By.XPATH, "//input[@name='session[username_or_email]']")
                    if login_prompt:
                        logger.error("login prompt detected - session definitely logged out")
                except NoSuchElementException:
                    logger.debug("no login prompt found, but tweet textarea missing - possible page load issue")
                # Tarayıcıyı temizle
                if S.clear_browsing_data():
                    logger.info("browsing data cleared successfully, ready for login")
                else:
                    logger.error("browsing data could not be cleared, login may be risky")
                time.sleep(randint(20, 40))
                return False

        except Exception as e:
            logger.error(f"session check error - {str(e)} - {datetime.now(tr_timezone).strftime('%Y-%m-%d %H:%M:%S')}")
            current_url = S.driver.current_url
            logger.debug(f"current URL during error: {current_url}")
            if S.clear_browsing_data():
                logger.info("browsing data cleared successfully, ready for login")
            else:
                logger.error("browsing data could not be cleared, login may be risky")
            time.sleep(randint(60, 120))
            return False

def unfollow_an_account(S, account):
    """Belirtilen hesabı takipten çıkar"""
    if len(account) > 15:
        logger.debug("wrong account, username too long")
        return True
    try:
        S.driver.get("https://x.com/"+account)
        element = WebDriverWait(S.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="placementTracking"]')))
        unfollow_button = S.driver.find_element(
            By.CSS_SELECTOR, '[data-testid="placementTracking"]')
        if unfollow_button.text != "Abonné" and unfollow_button.text != "Following":
            logger.debug(f"wrong account, username too long: {account}")
            return True
        unfollow_button.click()
        click_confirm = S.driver.find_element(
            By.CSS_SELECTOR, '[data-testid="confirmationSheetConfirm"]')
        click_confirm.click()
        logger.info(f"account unfollowed: {account}")
        return True
    except Exception as e:
        logger.error(f"unfollow error: {str(e)}")
        return False

def get_tweet_text(S, url):
    try:
        S.driver.get(url)
        element = WebDriverWait(S.driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetText"]')))
        tweet_text = str(element.text)
        logger.debug(f"tweet text: {tweet_text[:50]}...")
        return tweet_text
    except TimeoutException:
        logger.error(f"tweet text could not be retrieved: Timeout - url: {url}")
        return ""
    except NoSuchElementException:
        logger.error(f"tweet text could not be retrieved: element not found - url: {url}")
        return ""
    except Exception as e:
        logger.error(f"tweet text could not be retrieved: {str(e)} - url: {url}")
        return ""

def get_tweet_username(S, url):
    try:
        S.driver.get(url)
        element = WebDriverWait(S.driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="User-Name"]')))
        account = str(element.text).split("@")
        username = account[1] if len(account) > 1 else ""
        if username:
            logger.debug(f"tweet owner: @{username}")
        return username
    except TimeoutException:
        logger.error(f"tweet username could not be retrieved: timeout - url: {url}")
        return ""
    except NoSuchElementException:
        logger.error(f"tweet username could not be retrieved: element not found - url: {url}")
        return ""
    except Exception as e:
        logger.error(f"tweet username could not be retrieved: {str(e)} - url: {url}")
        return ""

def tweet_info_dict(selenium_session, url, process_giveaway=True):
    """
    Tweet bilgilerini işler ve döndürür, isteğe bağlı olarak giveaway işlemlerini gerçekleştirir
    Args:
        selenium_session: Selenium oturumu
        url: Tweet url'si
        process_giveaway (bool): Giveaway işlemleri yapılsın mı?
    Returns:
        dict: Username, text, url, etiket gereksinimleri ve takip edilecek hesapları içeren sözlük
    """
    try:
        logger.info(f"tweet info getting - url: {url}")
        tweet_info = get_tweet_info(selenium_session, url)

        username = tweet_info.get('username', '').strip().replace('Like', '')
        text = tweet_info.get('text', '').strip()
        tag_requirements = tweet_info.get('tag_requirements', 0)
        accounts_to_follow = tweet_info.get('accounts_to_follow', [])

        if not username or not text:
            logger.warning("tweet info missing or empty")
        
        result = {
            "username": username, 
            "text": text, 
            "url": url,
            "tag_requirements": tag_requirements,
            "accounts_to_follow": accounts_to_follow
        }

        # Giveaway işlemleri istenirse burada devam edilir
        if process_giveaway and username and text:
            try:
                d = Data()
                config = load_config()  # Konfigürasyonu yükleyin
                if is_valid_giveaway(result, config):
                    # Yorum oluştur (artık etiket gereksinimlerini biliyoruz)
                    comment = what_to_comment(text, selenium_session, url, tag_requirements)
                    if comment:
                        # Yorumu gönder ve etkileşimde bulun
                        interact_with_tweet(selenium_session, result, comment)
                        logger.info(f"giveaway successfully processed - url: {url}")
            except Exception as e:
                logger.info(f"Giveaway process error: {str(e)}")

        return result
    except Exception as e:
        logger.error(f"tweet info could not be retrieved: {str(e)}")
        return {"username": "x", "text": "x", "url": url, "tag_requirements": 0, "accounts_to_follow": []}

def get_tweet_info(selenium_session, url):
    """
    Tweet bilgilerini ve etiket gereksinimlerini tek seferde alır
    Args:
        selenium_session: Selenium oturumu
        url: Tweet url'si
    Returns:
        dict: Username, text, etiket gereksinimleri ve takip edilecek hesapları içeren sözlük
    """
    tweet_info_dict = {"username": "", "text": "", "tag_requirements": 0, "accounts_to_follow": []}
    
    try:
        if not url or not isinstance(url, str):
            logger.error("invalid tweet url")
            return tweet_info_dict

        logger.info(f"tweet page loading - url: {url}")
        selenium_session.driver.get(url)
        time.sleep(10)

        # Tweet container kontrolü
        try:
            tweet_container = WebDriverWait(selenium_session.driver, PAGE_LOAD_TIMEOUT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="cellInnerDiv"]'))
            )
        except TimeoutException:
            logger.error("tweet container not found")
            return tweet_info_dict

        # Tweet içeriği kontrolü
        try:
            tweet_element = WebDriverWait(selenium_session.driver, PAGE_LOAD_TIMEOUT).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweet"]'))
            )
        except TimeoutException:
            logger.error("tweet content not found")
            return tweet_info_dict

        _tweet_data = selenium_session.driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweet"]')
        _tweet_text = selenium_session.driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweetText"]')

        # Pozisyon bulma mantığı kaldırıldı, ilk tweet verisi kullanılıyor
        if _tweet_data and _tweet_text:
            tweet_data = str(_tweet_data[0].text).split("\n")  # İlk tweet verisi
            tweet_text = str(_tweet_text[0].text)  # İlk tweet metni

            usr = tweet_data[1] if len(tweet_data) > 1 and "@" in tweet_data[1] else tweet_data[0]
            username = usr.strip().lower()
            
            # Tweet sahibini kaydet
            logger.info(f"tweet owner added: {username}")
            
            # Etiket gereksinimlerini kontrol et
            tag_requirements = check_tag_requirements(tweet_text)
            
            # Takip edilecek hesapları bul
            accounts_to_follow = get_who_to_follow(selenium_session, url, tweet_text, username)
            
            # Hesapları logla
            logger.info("\naccounts to follow:")
            for account in accounts_to_follow:
                logger.info(f"- {account}")
            
            logger.debug(f"accounts to follow: {', '.join(accounts_to_follow)}...")
            
            result = {
                "username": username,
                "text": tweet_text.strip(),
                "tag_requirements": tag_requirements,
                "accounts_to_follow": accounts_to_follow
            }
            
            logger.debug(f"tweet info retrieved: @{username}")
            return result

        logger.warning("tweet content not found")
        return tweet_info_dict

    except StaleElementReferenceException:
        logger.warning("element stale - retrying...")
        time.sleep(randint(5, 10))
        return tweet_info_dict

    except TimeoutException:
        logger.warning("sayfa yükleme zaman aşımı")
        time.sleep(randint(5, 10))
        return tweet_info_dict

    except WebDriverException as e:
        if "rate limit" in str(e).lower():
            logger.warning(f"rate limit aşıldı. {RATE_LIMIT_DELAY} saniye bekleniyor...")
            time.sleep(randint(5, 10))
        else:
            logger.error(f"browser error: {str(e)}")
            time.sleep(randint(5, 10))
        return tweet_info_dict

    except Exception as e:
        logger.error(f"unexpected error: {str(e)}")
        time.sleep(randint(5, 10))
        return tweet_info_dict

def load_progress_data():
    """İlerleme verilerini yükler"""
    try:
        with open('progress.json', 'r') as f:
            progress_data = json.load(f)
            
        tweet_txt = progress_data.get('tweet_txt', [])
        crash_follow = progress_data.get('crash_follow', [])
        tt_follow = progress_data.get('tt_follow', [])
        t_follow = progress_data.get('t_follow', [])
        ttt_follow = progress_data.get('ttt_follow', [])
        tttt_follow = progress_data.get('tttt_follow', [])
        alph_follow = progress_data.get('alph_follow', [])
        idxx = progress_data.get('idxx', 0)
        follow_nbr = progress_data.get('follow_nbr', 0)
        giveaway_g = progress_data.get('giveaway_g', 0)
        giveaway_done = progress_data.get('giveaway_done', 0)
        operations_count = progress_data.get('operations_count', 0)
        
        logger.info("progress data loaded successfully")
        logger.debug(f"Loaded data: Tweet count={len(tweet_txt)}, follow count={follow_nbr}")
        return tweet_txt, crash_follow, tt_follow, t_follow, ttt_follow, tttt_follow, alph_follow, idxx, follow_nbr, giveaway_g, giveaway_done, operations_count
    except Exception as e:
        logger.error(f"progress data could not be loaded: {e}")
        return [], [], [], [], [], [], [], 0, 0, 0, 0, 0

def load_recent_urls():
    """Son url'leri yükler"""
    try:
        with open("recent_url.txt", "r") as file:
            tweet_from_url = file.read().splitlines()
        tweet_from_url = [url.strip() for url in tweet_from_url]
        logger.info(f"loaded url {len(tweet_from_url)} from recent_url.txt")
        return tweet_from_url
    except Exception as e:
        logger.error(f"recent_url.txt could not be loaded: {str(e)}")
        return []

def perform_follow_operations(S, tttt_follow, rate_limiter: TwitterRateLimiter, save_enabled, progress_data, username, password, current_user):
    """Takip işlemlerini gerçekleştirir"""
    total_follows = len(tttt_follow)
    follow_nbr = progress_data.get('follow_nbr', 0)
    alph_follow = progress_data.get('alph_follow', [])
    operations_count = progress_data.get('operations_count', 0)

    logger.info(f"follow operations started - {username}")
    logger.info(f"total follows: {total_follows}, current follow: {follow_nbr}")

    for i in range(follow_nbr, total_follows):
        try:
            logger.debug(f"follow operation - target: {tttt_follow[i]} ({i+1}/{total_follows})")
            follow_success = follow_an_account(S, tttt_follow[i], 2, username, password, rate_limiter)
            
            if follow_success:
                follow_nbr += 1
                alph_follow.append(tttt_follow[i].lower())
                operations_count += 1
                logger.info(f"Takip başarılı: {tttt_follow[i]} ({follow_nbr}/{total_follows})")
                
                if operations_count % 5 == 0 and save_enabled:
                    progress_data.update({
                        "follow_nbr": follow_nbr,
                        "alph_follow": alph_follow,
                        "operations_count": operations_count    
                    })
                    save_progress(progress_data, current_user)
                    logger.debug(f"progress saved - follow count: {follow_nbr}")
            
            time.sleep(S.wait_time)
            
        except Exception as e:
            logger.error(f"follow operation error - target: {tttt_follow[i]}, error: {str(e)}")
            time.sleep(S.wait_time)
            continue

    logger.info(f"follow operations completed - total follows: {follow_nbr}")
    return follow_nbr, alph_follow, operations_count

def perform_like_operations(S, tweet_from_url, t_comment_or_not, t_full_comment, username, save_enabled, progress_data, current_user):
    """Like ve etkileşim işlemlerini gerçekleştirir"""
    giveaway_g = progress_data.get('giveaway_g', 0)
    giveaway_done = progress_data.get('giveaway_done', 0)
    idxx = progress_data.get('idxx', 0)
    operations_count = progress_data.get('operations_count', 0)

    logger.info(f"like operations started - {username}")
    logger.info(f"tweet to be processed: {len(tweet_from_url)}")
    for t in tweet_from_url:
        if not t.strip():
            continue

        logger.debug(f"tweet is being processed ({giveaway_g + 1}/{len(tweet_from_url)}): {t}")
        
        like = like_a_tweet(S, t, TwitterRateLimiter(username))
        time.sleep(S.wait_time)    

        if like:
            giveaway_done += 1
            giveaway_g += 1
            retweet_a_tweet(S, t, TwitterRateLimiter(username))
            operations_count += 1
            
            try:
                if t_comment_or_not[idxx]:
                    comment_success = comment_a_tweet(S, t, t_full_comment[idxx], TwitterRateLimiter(username))
                    if comment_success:
                        logger.info(f"tweet was commented: {t_full_comment[idxx][:50]}...")
                    operations_count += 1
                    time.sleep(randint(5, 10))
            except Exception as e:
                logger.error(f"commenting error: {str(e)}")

            if operations_count % 5 == 0 and save_enabled:
                progress_data.update({
                    "giveaway_g": giveaway_g,
                    "giveaway_done": giveaway_done,
                    "operations_count": operations_count
                })
                save_progress(progress_data, current_user)
                logger.debug(f"progress saved - operations count: {operations_count}")
        else:
            giveaway_done += 1
            logger.debug("tweet already liked")
            time.sleep(3)

        if giveaway_g % 10 == 0 and giveaway_g > 1:
            logger.info("90 minute waiting time")
            time.sleep(5400)

        idxx += 1

    logger.info(f"like operations completed - total: {giveaway_g}/{giveaway_done}")
    return giveaway_g, giveaway_done, idxx, operations_count 

def get_who_to_follow(S, url, text, username):
    """Tweet'ten takip edilecek kullanıcıları alır"""
    if not url or not isinstance(url, str):
        logger.warning(f"invalid url: {url}")
        return []
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        logger.debug(f"URL corrected: {url}")

    if not url.startswith("https://x.com/") and not url.startswith("https://twitter.com/"):
        logger.error(f"invalid tweet url: {url}")
        return []
        
    try:
        S.driver.get(url)
        logger.debug(f"tweet page opened: {url}")

        # Kullanıcı adı ve metin temizleme
        cleaned_username = username.strip() if username else ""
        cleaned_text = text.strip() if text else ""  # replace("", " ") kaldırıldı

        # Takip edilecek hesapları al
        account_list = list_of_account_to_follow(cleaned_username, cleaned_text)

        if account_list:
            accounts = account_list.split()
            valid_accounts = []
            for acc in accounts:
                clean_acc = clean_username(acc)
                if clean_acc and clean_acc not in COMMON_WORDS:
                    valid_accounts.append(clean_acc)

            unique_accounts = list(set(valid_accounts))
            logger.debug(f"account list: {', '.join(unique_accounts[:5])}...")
            return unique_accounts

        logger.warning("no accounts to follow")
        return []

    except Exception as e:
        logger.error(f"error getting accounts to follow: {str(e)}")
        return []

def get_elem_from_list(list_, elem_):
    """Listeden belirli bir elemanı içeren öğeyi bulur"""
    if not list_ or not elem_:
        logger.debug("empty list or element")
        return ""
        
    try:
        for item in list_:
            if isinstance(item, str) and elem_ in item:
                logger.debug(f"element found: {item}")
                return item
        logger.debug(f"element not found: {elem_}")
        return ""
    except Exception as e:
        logger.error(f"List search error: {str(e)}")
        return ""

def parse_number(num):
    """Sayısal değerleri parse eder (K, M, B gibi)"""
    try:
        num = str(num).lower()
        original = num
        
        if "b" in num:
            if "." in num:
                num = num.replace(".", "").replace("b", "") + "00000000"
            else:
                num = num.replace("b", "") + "000000000"
            logger.debug(f"billion converted into value: {original} -> {num}")

        elif "m" in num:
            if "." in num:
                num = num.replace(".", "").replace("m", "") + "00000"
            else:
                num = num.replace("m", "") + "000000"
            logger.debug(f"million converted into value: {original} -> {num}")

        elif "k" in num:
            if "." in num:
                num = num.replace(".", "").replace("k", "") + "00"
            else:
                num = num.replace("k", "") + "000"
            logger.debug(f"k converted into value: {original} -> {num}")
        else:
            num = num.replace(".", "").replace(",", "")
            logger.debug(f"number cleaned: {original} -> {num}")

        return num
    except Exception as e:
        logger.error(f"number parse error: {str(e)}")
        return "0"

def get_list_of_my_followings(S, user):
    """Kullanıcının takip ettiği hesapları listeler"""
    try:
        nb_of_followings = get_user_following_count(S, user)
        logger.info(f"number of accounts monitored: {nb_of_followings}")
        
        S.driver.implicitly_wait(15)
        S.driver.get(f"https://x.com/{user}/following")
        logger.debug(f"following page opened: {user}")

        run = True
        list_of_user = []
        selenium_data = []
        account = ""
        nb = 0
        data_list = []

        while run:
            try:
                element = WebDriverWait(S.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="UserCell"]')))
                tweets_username = S.driver.find_elements(
                    By.CSS_SELECTOR, '[data-testid="UserCell"]')
                last_user = tweets_username[len(tweets_username) - 1]

                if nb >= nb_of_followings or are_last_x_elements_same(data_list, 350) or nb > 1000:
                    logger.info(f"total {len(list_of_user)} followed accounts found")
                    return list_of_user

                for tweet_username in tweets_username:
                    if tweet_username not in selenium_data:
                        try:
                            parsing_user = str(tweet_username.text).split("")
                            account = parsing_user[1]
                            clean_account = account.replace("@", "")
                            list_of_user.append(clean_account)
                            selenium_data.append(tweet_username)
                            S.driver.execute_script(
                                "arguments[0].scrollIntoView();", tweet_username)
                            nb += 1
                            time.sleep(3)
                            data_list.append(len(list_of_user))
                            logger.debug(f"account added: {clean_account} ({nb})")
                        except:
                            time.sleep(3)
                            pass
            except Exception as e:
                logger.error(f"following list get error: {str(e)}")
                return list_of_user

        return list_of_user
    except Exception as e:
        logger.error(f"following list get error: {str(e)}")
        return False

def get_user_following_count(S, user):
    """Kullanıcının takip ettiği kişi sayısını alır"""
    try:
        S.driver.implicitly_wait(15)
        S.driver.get(f"https://x.com/{user}")
        logger.debug(f"following page opened: {user}")

        element = WebDriverWait(S.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="UserName"]')))

        try:
            following_count = S.driver.find_element(
                By.XPATH, "/html/body/div[1]/div/div/div[2]/main/div/div/div/div/div/div[3]/div/div/div/div/div[5]/div[1]/a/span[1]/span")
            following_count = following_count.text.replace(" ", "")
            following_count = parse_number(following_count)
            count = int(following_count)
            logger.info(f"number of followed people: {count} - {user}")
            return count
        except:
            try:
                # Alternatif yöntem
                following_text = get_elem_from_list(
                    S.driver.find_element(By.CSS_SELECTOR, '[data-testid="primaryColumn"]')
                    .text.split(""), 
                    "abonnements"
                )
                if not following_text:
                    following_text = get_elem_from_list(
                        S.driver.find_element(By.CSS_SELECTOR, '[data-testid="primaryColumn"]')
                        .text.split(""),
                        "Following"
                    ).split(" ")[0]
                
                count = int(parse_number(following_text))
                logger.info(f"number of followed people (alternative): {count} - {user}")
                return count
            except:
                logger.error(f"number of followers not found: {user}")
                return -1

    except Exception as e:
        logger.error(f"following count get error: {str(e)}")
        return -1

def forever_loop():
    """Ana döngü fonksiyonu"""
    while True:
        try:
            logger.info("initializing the main loop...")
            main_one()
            logger.info("main loop completed, sleeping for 5 minutes")
            time.sleep(300)
        except Exception as e:
            logger.error(f"main loop error: {str(e)}")
            logger.info("1 minute sleep and retry")
            time.sleep(60)
            continue

def get_only_account(s):
    """Liste içindeki @ ile başlayan kullanıcı adlarını döndürür"""
    try:
        accounts = [item for item in s if isinstance(item, str) and item.startswith("@")]
        logger.debug(f"@ starting with {len(accounts)} account found")
        return accounts
    except Exception as e:
        logger.error(f"account filter error: {str(e)}")
        return []

def save_progress(data, filename=None):
    """İşlem durumunu dosyaya kaydeder"""
    if filename is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        filename = os.path.join(script_dir, "progress.json")

    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info(f"progress saved: {filename}")
        logger.debug(f"saved data: tweet count={len(data.get('tweet_txt', []))}, "
                     f"follow count={data.get('follow_nbr', 0)}")
    except Exception as e:
        logger.error(f"progress save failed: {str(e)}")

def retry_like_operation(S, username, password, url, rate_limiter: TwitterRateLimiter, max_retries=3):
    """Like operation retry mechanism"""
    for attempt in range(max_retries):
        try:
            like_result = like_a_tweet(S, url, rate_limiter)
            if like_result:
                logger.info(f"liked the tweet - trial {attempt + 1}")
                return True
        except Exception as e:
            logger.warning(f"like trial {attempt + 1}/{max_retries} failed: {str(e)}")
            time.sleep(randint(2, 5))
            
            # Oturum kontrolü ve yeniden giriş
            if not is_account_log_out(S):
                try:
                    try_login_again(S, username, password)
                except Exception as login_error:
                    logger.error(f"login again failed: {str(login_error)}")
                    
        time.sleep(randint(3, 7))
    
    logger.error(f"tweet like failed ({max_retries} attempts) - url: {url}")
    return False

def retry_retweet_operation(S, username, password, url, rate_limiter: TwitterRateLimiter, max_retries=3):
    """Retweet işlemi için yeniden deneme mekanizması"""
    for attempt in range(max_retries):
        try:
            retweet_result = retweet_a_tweet(S, url, rate_limiter)
            if retweet_result:
                logger.info(f"tweet retweetlendi - trial {attempt + 1}")
                return True
        except Exception as e:
            logger.warning(f"retweet trial {attempt + 1}/{max_retries} failed: {str(e)}")
            time.sleep(randint(2, 5))
            
            # Oturum kontrolü ve yeniden giriş
            if not is_account_log_out(S):
                try:
                    try_login_again(S, username, password)
                except Exception as login_error:
                    logger.error(f"login again failed: {str(login_error)}")
                    
        time.sleep(randint(3, 7))

    logger.error(f"failed to retweet tweet (after {max_retries} attempts) - url: {url}")
    return False

def retry_comment_operation(S, username, password, url, comment_text, rate_limiter: TwitterRateLimiter, max_retries=3):
    """Yorum işlemi için yeniden deneme mekanizması"""
    for attempt in range(max_retries):
        try:
            comment_result = comment_a_tweet(S, url, comment_text, rate_limiter)
            if comment_result:
                logger.info(f"commented - trial {attempt + 1}")
                logger.debug(f"comment text: {comment_text[:50]}...")
                return True
        except Exception as e:
            logger.warning(f"comment trial {attempt + 1}/{max_retries} failed: {str(e)}")
            time.sleep(randint(2, 5))
            
            # Oturum kontrolü ve yeniden giriş
            if not is_account_log_out(S):
                try:
                    try_login_again(S, username, password)
                except Exception as login_error:
                    logger.error(f"login again failed: {str(login_error)}")
                    
        time.sleep(randint(3, 7))

    logger.error(f"failed to comment (after {max_retries} attempts) - url: {url}")
    return False

def retry_follow_operation(S, account_name, username, password, max_retries, rate_limiter: TwitterRateLimiter):
    """Takip işlemi için yeniden deneme mekanizması"""
    for attempt in range(max_retries):
        try:
            # Oturum kontrolü
            if not is_account_log_out(S):
                logger.debug(f"logging out - {username}")
                try_login_again(S, username, password)
                
            # Takip işlemini dene
            follow_result = follow_an_account(
                S=S,
                account_name=account_name,
                max_retries=2,
                username=username,
                password=password,
                rate_limiter=rate_limiter
            )
            
            if follow_result:
                logger.info(f"account followed: {account_name}")
                return True
                
        except Exception as e:
            logger.warning(f"follow trial {attempt + 1}/{max_retries} failed: {str(e)}")
            time.sleep(5)
            
    logger.error(f"account not followed (after {max_retries} attempts): {account_name}")
    return False

def check_rate_limit(username: str, action_type: str = None) -> bool:
    """
    Tüm işlem tipleri için genel rate limit kontrolü
    
    Args:
        username (str): Kullanıcı adı
        action_type (str, optional): İşlem tipi ('follow', 'like', 'retweet', 'comment')
                                   None ise tüm işlem tipleri kontrol edilir
    
    Returns:
        bool: Rate limit aşıldıysa True, değilse False
    """
    try:
        limiter = TwitterRateLimiter(username)
        
        # Kontrol edilecek işlem tiplerini belirle
        if action_type:
            action_types = [action_type]
        else:
            action_types = ['follow', 'like', 'retweet', 'comment']
            
        for action in action_types:
            if limiter.is_rate_limited(action):
                wait_time = limiter.get_wait_time(action)
                if wait_time > 0:
                    logger.info("="*50)
                    logger.warning(f"{action.capitalize()} for rate limit exceeded.")
                    logger.info(f"wait time: {wait_time} seconds")
                    
                    # Saatlik/günlük limit durumunu logla
                    hourly_count = limiter.request_counts['hourly'].get(action, 0)
                    daily_count = limiter.request_counts['daily'].get(action, 0)
                    hourly_limit = limiter.limits[action]['hourly']
                    daily_limit = limiter.limits[action]['daily']
                    
                    logger.info(f"hourly: {hourly_count}/{hourly_limit}")
                    logger.info(f"daily: {daily_count}/{daily_limit}")
                    logger.info("="*50)
                    
                    time.sleep(wait_time)
                    return True
                    
        return False
        
    except Exception as e:
        logger.error("="*50)
        logger.error(f"error in rate limit control: {str(e)}")
        logger.error("="*50)
        time.sleep(60)  # Hata durumunda 1 dakika bekle
        return True

def cleanup_session():
    global S
    if S is not None:
        try:
            S.close()  # Oturumu kapat ve tarayıcıyı temiz şekilde sonlandır
            logger.info("session and browser cleaned")
        except Exception as e:
            logger.error(f"session and browser cleanup error: {str(e)}")
    S = None

def main_one():
    """Ana program fonksiyonu"""
    global S
    S = None
    import os
    import json
    from datetime import datetime
    import time
    from random import randint
    import yaml
    import sys    

    # Değişkenleri tanımla
    add_sentence_to_tag = []
    random_rt_and_tweet = False
    random_tweet_nb = 0
    random_retweet_nb = 0
    sentence_to_tweet = []
    human = False
    random_action = False
    tweet_txt = []
    crash_follow = []
    t_follow = []
    t_comment_or_not = []
    t_full_comment = []
    alph_follow = []
    idxx = 0
    follow_nbr = 0
    giveaway_g = 0
    giveaway_done = 0
    operations_count = 0

    # Yardımcı fonksiyonlar
    def update_step(new_step):
        nonlocal step
        step = new_step
        if save_enabled and progress_file:
            progress_data["step"] = step
            save_progress(progress_data, current_user)
            logger.debug(f"step updated: {step}")

    def log_status(message="", show_separator=True):
        """Standart format için yardımcı fonksiyon"""
        current_time = datetime.now(tr_timezone).strftime('%Y-%m-%d %H:%M:%S')
        if show_separator:
            logger.info("="*50)
        if message:
            logger.info(f"{current_time} - {message}")
        if show_separator:
            logger.info("="*50)

    # Yapılandırma yükleme
    try:
        with open('configuration.yml', 'r', encoding='utf-8') as file:
            data = yaml.safe_load(file)
            username_info = data["account_username"]
            password_info = data["account_password"]
            sentence_to_tweet = data["sentence_to_tweet"]
            random_rt_and_tweet = data["random_retweet_and_tweet"]
            random_tweet_nb = data["random_tweet_nb"]
            random_retweet_nb = data["random_retweet_nb"]
            crash_or_no = data["crash_or_no"]
            random_action = data["random_action"]
            human = data["human"]
            add_sentence_to_tag = data["add_sentence_to_tag"]

            if isinstance(username_info, str):
                username_info = [username_info]
            if len(username_info) != len(password_info):
                logger.critical("username and password counts do not match")
                sys.exit(1)
        logger.info("configuration.yml loaded successfully")
    except Exception as e:
        logger.critical(f"configuration file could not be loaded: {str(e)}")
        sys.exit(1)

    # Dosya yolu ayarları
    script_dir = os.path.dirname(os.path.abspath(__file__))
    progress_file = os.path.join(script_dir, "progress.json")

    # Ortak değişkenler
    current_user = username_info[0]
    step = "initial"
    progress_data = {
        "current_user": current_user,
        "step": step,
        "tweet_txt": tweet_txt,
        "crash_follow": crash_follow,
        "t_follow": t_follow,
        "alph_follow": alph_follow,
        "idxx": idxx,
        "follow_nbr": follow_nbr,
        "giveaway_g": giveaway_g,
        "giveaway_done": giveaway_done,
        "operations_count": operations_count
    }

    # Progress dosyası kontrolü
    if crash_or_no and os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as file:
                saved_progress = json.load(file)
                if saved_progress:
                    log_status("previous progress found. do you want to load it?")
                    logger.info("yes = y")
                    logger.info("no = n")
                    load_choice = input().strip().lower()
                    if load_choice == 'y':
                        current_user = saved_progress.get("current_user", current_user)
                        step = saved_progress.get("step", "initial")
                        tweet_txt = saved_progress.get("tweet_txt", [])
                        crash_follow = saved_progress.get("crash_follow", [])
                        t_follow = saved_progress.get("t_follow", [])
                        alph_follow = saved_progress.get("alph_follow", [])
                        idxx = saved_progress.get("idxx", 0)
                        follow_nbr = saved_progress.get("follow_nbr", 0)
                        giveaway_g = saved_progress.get("giveaway_g", 0)
                        giveaway_done = saved_progress.get("giveaway_done", 0)
                        operations_count = saved_progress.get("operations_count", 0)
                        log_status("previous progress loaded")
        except Exception as e:
            logger.error(f"error loading progress file: {str(e)}")

    # Progress save choice
    log_status("save progress for all sessions?")
    logger.info("yes = y")
    logger.info("no = n")
    save_choice = input().strip().lower()
    save_enabled = save_choice == 'y'

    if save_enabled:
        log_status("progress saving active for all sessions")
        try:
            with open(progress_file, 'w', encoding='utf-8') as file:
                json.dump({}, file)
            logger.info(f"progress file created for: {current_user}")
        except Exception as e:
            logger.error(f"error creating progress file: {str(e)}")
    else:
        log_status("[warning] progress saving disabled for all sessions")

    # Hesap döngüsü
    for i in range(len(username_info)):
        current_user = username_info[i]
        current_pass = password_info[i]
        rate_limiter = TwitterRateLimiter(current_user)
        S = Scraper(username=current_user)
        try:
            update_step("login")
            logger.info("="*50)
            logger.info(f"starting new session for: {current_user}")
            logger.info("="*50)

            # Her hesap için yeni Scraper örneği
            S = Scraper(username=current_user)

            # Rate limiter başlatma ve kontrol
            rate_limiter = TwitterRateLimiter(current_user)
            logger.info(f"Rate limiter initialized for: {current_user}")
            if check_rate_limit(current_user):
                logger.warning(f"Rate limit active for {current_user}")
                logger.info(f"Waiting for rate limit reset...")
                wait_time = rate_limiter.get_wait_time('follow')
                time.sleep(wait_time)
                if S is not None:
                    S.close()
                continue

            logger.info("[1/3] browser preparing...")
            logger.info("[2/3] cookies cleaning...")
            S.driver.delete_all_cookies()
            logger.info("[3/3] cache cleaning...")
            S.clear_browsing_data()
            logger.info("browser ready")
            time.sleep(2)

            logger.info("[1/4] logging in...")
            if not login(S, current_user, current_pass):
                logger.warning(f"[{current_user}] ilk giriş denemesi başarısız, yeniden deneniyor...")
                if not try_login_again(S, current_user, current_pass):
                    logger.error(f"login failed after retries: {current_user}")
                    if S is not None:
                        S.close()
                        S = None
                    continue
            else:
                logger.info(f"[{current_user}] first entry successful")

            logger.info("[2/4] session control...")
            if not check_login_good(S):
                logger.error(f"session verification failed: {current_user}")
                logger.warning("this account will be skipped...")
                if S is not None:
                    S.close()
                    S = None
                continue

            logger.info("[3/4] accepting cookies...")
            accept_cookie(S)
            time.sleep(S.wait_time)    
            logger.info("[4/4] accepting notifications...")
            accept_notification(S)
            time.sleep(S.wait_time)

            logger.info("final verifications in progress...")
            login_successful = False
            for attempt in range(2):
                if check_if_good_account_login(S, current_user):
                    login_successful = True
                    break
                logger.warning(f"trying to login again... (attempt {attempt+1}/2)")
                time.sleep(3)
                if S is not None:
                    S.close()
                S = Scraper(username=current_user)
                if login(S, current_user, current_pass) and check_login_good(S):
                    accept_cookie(S)
                    accept_notification(S)
                    login_successful = True
                    break

            if not login_successful:
                logger.error(f"could not establish session: {current_user}")
                if S is not None:
                    S.close()
                continue

            current_time = datetime.now(tr_timezone).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"{current_time}")

            logger.info("redirecting to notifications tab...")
            if not S.click_notifications_tab():
                logger.error(f"failed to open notifications tab: {current_user}")
                if S is not None:
                    S.close()
                continue

            update_step("initial_checks")
            logger.info(f"session ready for: {current_user}")
            logger.info("="*50)

            # Takip ve giveaway işlemleri
            tweet_from_url = []
            giveaway_g = 0
            follow_nbr = 0
            nb_of_following_t1 = 0
            less_than_4500 = 0
            big_follow = 0

            for j in range(2):
                x = get_user_following_count(S, username_info[i])
                if x == -1:
                    big_follow += 10000
                    logger.warning(f"could not get follower count - attempt {j+1}/5")
                elif x < 4500 or x > 9999:
                    less_than_4500 += 1
                    logger.debug(f"follower count outside limits: {x}")
                else:
                    big_follow = x
                    logger.info(f"follower count: {x}")
                    break

            if big_follow >= 10000 * 5:
                logger.error(f"{username_info[i]} has issues - skipping account")
                if S is not None:
                    S.close()
                continue

            if less_than_4500 >= 3:
                nb_of_following_t1 = 1
                logger.debug("follower count less than 4500")
            else:
                nb_of_following_t1 = big_follow + 1
                logger.debug(f"follower count acceptable: {big_follow}")

            if nb_of_following_t1 >= 4500:
                logger.info("starting unfollow process...")
                all_my_following = get_list_of_my_followings(S, username_info[i])
                time.sleep(randint(300, 600))
                
                if all_my_following:
                    toto_follow = len(all_my_following) - 1
                    tototo_follow = randint(90, 100)
                    if toto_follow < 90:
                        tototo_follow = toto_follow - 1
                    
                    logger.info(f"accounts to unfollow: {tototo_follow}")
                    skip_un = False
                    error_uf = 0
                    for j in range(tototo_follow):
                        if skip_un:
                            logger.warning("skipping unfollow - too many errors")
                            break
                        try:
                            account_to_unfollow = all_my_following[len(all_my_following) - 1 - j]
                            logger.debug(f"unfollow target: {account_to_unfollow}")
                            uf = unfollow_an_account(S, account_to_unfollow)
                            if not uf:
                                error_uf += 1
                                logger.warning(f"unfollow failed - Error count: {error_uf}")
                            else:
                                error_uf = 0
                            if error_uf > 9:
                                skip_un = True
                                logger.error("too many unfollow errors - stopping process")
                                break
                            time.sleep(randint(5, 10))
                        except Exception as e:
                            logger.error(f"Unfollow operation error: {str(e)}")
                            continue
                    
                    nb_of_following_t2 = get_user_following_count(S, username_info[i])
                    logger.info(f"unfollow completed - cleaned: {nb_of_following_t1 - nb_of_following_t2}")
                    logger.info(f"new following count: {nb_of_following_t2}")
                    logger.info("waiting 2 minutes for rate limit")
                    time.sleep(randint(60 * 2, 60 * 3))

            # crash_or_no durumuna göre URL'leri yükle
            if crash_or_no:
                tweet_from_url = load_recent_urls()
                logger.info(f"number of urls loaded: {len(tweet_from_url)}")
            else:
                if i == 0:
                    logger.info("[url] getting giveaway urls for first account...")
                    tweet_from_url = get_giveaway_url(S)
                    try:
                        with open("recent_url.txt", "w") as f:
                            for url in tweet_from_url:
                                f.write(url + "\n")
                        logger.info(f"saved {len(tweet_from_url)} urls to recent_url.txt")
                    except Exception as e:
                        logger.error(f"error saving urls: {str(e)}")
                tweet_from_url = print_file_info("recent_url.txt").split("\n")
                logger.info(f"loaded {len(tweet_from_url)} urls from recent_url.txt")

            rate_limiter = TwitterRateLimiter(current_user)
            tweet_requirements = []
            t_follow = []
            t_comment_or_not = []
            t_full_comment = []
            all_tag_accounts = data.get("accounts_to_tag", []) + data.get("accounts_to_tag_more", [])
            sentence_for_tag = data.get("sentence_for_tag", [])
            sentence_for_random_comment = data.get("sentence_for_random_comment", [])

            for url in tweet_from_url:
                if url.strip():
                    try:
                        S.driver.get(url)
                        time.sleep(3)
                        tweet_content = S.driver.find_element(By.XPATH, "//article//div[@lang]").text
                        reqs = process_tweet_requirements(tweet_content, url, all_tag_accounts, rate_limiter, add_sentence_to_tag, sentence_for_tag, sentence_for_random_comment)
                        tweet_requirements.append(reqs)
                        tweet_txt.append(tweet_content)
                        crash_follow.append(url.split("/")[3])
                        t_follow.extend(reqs["follow_accounts"])
                        t_comment_or_not.append("comment" in reqs and reqs["comment"] is not None)
                        t_full_comment.append(reqs.get("comment", ""))
                        logger.debug(f"tweet processed: {url}")
                        time.sleep(randint(5, 10))
                    except Exception as e:
                        logger.error(f"could not process tweet: {str(e)}")
                        continue

            t_follow = list(dict.fromkeys(t_follow))
            t_follow = [x.strip() for x in t_follow if x.strip()]
            logger.info(f"unique accounts to follow: {len(t_follow)}")
            logger.info("accounts to follow:")
            for account in t_follow:
                logger.info(f" - {account}")

            update_step("following")
            logger.debug("starting follow operations...")
            for account in t_follow:
                try:
                    if not rate_limiter.can_perform_action('follow'):
                        wait_time = rate_limiter.get_wait_time('follow')
                        if wait_time > 0:
                            logger.warning(f"follow limit reached. Waiting {wait_time} seconds...")
                            time.sleep(wait_time)
                        continue
                        
                    # Önce normal follow dene, başarısız olursa retry mekanizmasını kullan
                    if not follow_an_account(S, account, 2, current_user, current_pass, rate_limiter):
                        if retry_follow_operation(S, account, current_user, current_pass, 3, rate_limiter):
                            follow_nbr += 1
                            alph_follow.append(account.lower())
                            logger.info(f"successfully followed after retry: {account}")
                        else:
                            logger.warning(f"failed to follow even after retries: {account}")
                    else:
                        follow_nbr += 1
                        alph_follow.append(account.lower())
                        logger.info(f"successfully followed: {account}")
                        
                    time.sleep(randint(5, 10))
                        
                except Exception as e:
                    logger.error(f"follow operation error: {str(e)}")
                    continue

            update_step("giveaway")
            logger.debug("starting giveaway operations...")
            for idx, reqs in enumerate(tweet_requirements):
                try:
                    if giveaway_g % 2 == 0:
                        S.driver.refresh()
                        time.sleep(3)
                        S.wait_for_page_load()
                        if not is_account_log_out(S):
                            logger.info("[session] account session closed, trying to log in again")
                            try_login_again(S, current_user, current_pass)
                            logger.info("session refreshed and logged in again")

                    current_url = tweet_from_url[idx]
                    
                    # Önce normal like dene, başarısız olursa retry mekanizmasını kullan
                    if not like_a_tweet(S, current_url, rate_limiter):
                        if retry_like_operation(S, current_user, current_pass, current_url, rate_limiter):
                            logger.success(f"liked after retry: {current_url}")
                            giveaway_done += 1
                        else:
                            logger.warning(f"like failed even after retries: {current_url}")
                    else:
                        logger.success(f"liked: {current_url}")
                        giveaway_done += 1

                    # Önce normal retweet dene, başarısız olursa retry mekanizmasını kullan
                    if not retweet_a_tweet(S, current_url, rate_limiter):
                        if retry_retweet_operation(S, current_user, current_pass, current_url, rate_limiter):
                            logger.success(f"retweeted after retry: {current_url}")
                        else:
                            logger.warning(f"retweet failed even after retries: {current_url}")
                    else:
                        logger.success(f"retweeted: {current_url}")

                    # Yorum gerekiyorsa, önce normal yorum dene, başarısız olursa retry mekanizmasını kullan
                    if t_comment_or_not[idx] and t_full_comment[idx]:
                        if not comment_a_tweet(S, current_url, t_full_comment[idx], rate_limiter):
                            if retry_comment_operation(S, current_user, current_pass, current_url, t_full_comment[idx], rate_limiter):
                                logger.success(f"comment posted after retry: {t_full_comment[idx]}")
                            else:
                                logger.warning(f"comment failed even after retries: {current_url}")
                        else:
                            logger.success(f"comment posted: {t_full_comment[idx]}")

                    giveaway_g += 1
                    time.sleep(randint(5, 10))

                    if operations_count % 5 == 0 and save_enabled:
                        progress_data.update({
                            "current_user": current_user,
                            "step": "giveaway_operation",
                            "tweet_txt": tweet_txt,
                            "crash_follow": crash_follow,
                            "t_follow": t_follow,
                            "alph_follow": alph_follow,
                            "idxx": idxx,
                            "follow_nbr": follow_nbr,
                            "giveaway_g": giveaway_g,
                            "giveaway_done": giveaway_done,
                            "operations_count": operations_count
                        })
                        save_progress(progress_data, current_user)
                        logger.debug("Progress saved")
                except Exception as e:
                    logger.error(f"giveaway operation error: {str(e)}")
                    continue

            # sentence_to_tweet listesinden rastgele tweet paylaşımı
            logger.debug(f"starting tweet operations for {current_user}")
            if random_rt_and_tweet and sentence_to_tweet and len(sentence_to_tweet) > 0:
                tweet_count = min(random_tweet_nb, len(sentence_to_tweet)) if random_tweet_nb > 0 else 1
                logger.info(f"Posting {tweet_count} tweets from sentence_to_tweet for {current_user}")
                for _ in range(tweet_count):
                    tweet_text = sentence_to_tweet[randint(0, len(sentence_to_tweet) - 1)]
                    if make_a_tweet(S, tweet_text):
                        logger.success(f"Tweet posted: {tweet_text}")
                    else:
                        logger.error(f"Failed to post tweet: {tweet_text}")
                    time.sleep(randint(5, 10))
            else:
                logger.info(f"No tweets posted for {current_user} - random_rt_and_tweet: {random_rt_and_tweet}, sentence_to_tweet: {len(sentence_to_tweet)}")

            logger.debug(f"starting random RT and fav operations for {current_user}")
            perform_random_tweet_rt(S, rate_limiter, random_action, random_tweet_nb, random_retweet_nb, sentence_to_tweet)

            if save_enabled:
                progress_data = {
                    "current_user": "",
                    "step": "initial",
                    "tweet_txt": [],
                    "crash_follow": [],
                    "t_follow": [],
                    "alph_follow": [],
                    "idxx": 0,
                    "follow_nbr": 0,
                    "giveaway_g": 0,
                    "giveaway_done": 0,
                    "operations_count": 0
                }
                save_progress(progress_data, current_user)
                logger.info(f"progress reset for {current_user}")

            tweet_txt = []
            crash_follow = []
            t_follow = []
            t_comment_or_not = []
            t_full_comment = []
            alph_follow = []
            idxx = 0
            follow_nbr = 0
            giveaway_g = 0
            giveaway_done = 0
            operations_count = 0

            if S is not None:
                if not S.close():
                    logger.warning(f"Failed to close session cleanly for {current_user}, forcing quit")
                    S.quit()
                else:
                    logger.info(f"{current_user} session closed successfully")
                S = None
                time.sleep(5)

            if i < len(username_info) - 1:
                wait_time = randint(5, 10)
                logger.info(f"waiting {wait_time} seconds before next account...")
                time.sleep(wait_time)

        except Exception as e:
            logger.error(f"Error occurred for {current_user}: {str(e)}")
            if S is not None:
                if not S.close():
                    logger.warning(f"Failed to close session cleanly for {current_user}, forcing quit")
                    S.quit()
                S = None
            continue

    logger.info("All accounts processed successfully")
    sys.exit(0)