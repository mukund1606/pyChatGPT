from selenium.webdriver.support import expected_conditions as EC
from selenium.common import exceptions as SeleniumExceptions
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By

import undetected_chromedriver as uc
from markdownify import markdownify
from threading import Thread
import platform
import logging
import weakref
import json
import time
import re
import os


cf_challenge_form = (By.ID, "challenge-form")

chatgpt_textbox = (By.TAG_NAME, "textarea")
chatgpt_streaming = (By.CLASS_NAME, "result-streaming")
chatgpt_big_response = (By.XPATH, '//div[@class="flex-1 overflow-hidden"]//div[p]')
chatgpt_small_response = (
    By.XPATH,
    '//div[starts-with(@class, "markdown prose w-full break-words")]',
)
chatgpt_alert = (By.XPATH, '//div[@role="alert"]')
chatgpt_intro = (By.ID, "headlessui-portal-root")
chatgpt_login_btn = (By.XPATH, '//button[text()="Log in"]')
chatgpt_login_h1 = (By.XPATH, '//h1[text()="Welcome back"]')
chatgpt_logged_h1 = (By.XPATH, '//h1[text()="ChatGPT"]')

chatgpt_new_chat = (By.LINK_TEXT, "New chat")
chatgpt_clear_convo = (By.LINK_TEXT, "Clear conversations")
chatgpt_confirm_clear_convo = (By.LINK_TEXT, "Confirm clear conversations")
chatgpt_chats_list_first_node = (
    By.XPATH,
    '//div[substring(@class, string-length(@class) - string-length("text-sm") + 1)  = "text-sm"]//a',
)

chatgpt_chat_url = "https://chat.openai.com/chat"


class ChatGPT:
    """
    An unofficial Python wrapper for OpenAI's ChatGPT API
    """

    def __init__(
        self,
        session_token: str | None = None,
        conversation_id: str = "",
        auth_type: str | None = None,
        email: str | None = None,
        password: str | None = None,
        login_cookies_path: str = "",
        captcha_solver: str = "pypasser",
        solver_apikey: str = "",
        proxy: str | None = None,
        chrome_args: list = [],
        moderation: bool = True,
        verbose: bool = False,
    ):
        """
        Initialize the ChatGPT object\n
        :param session_token: The session token to use for authentication
        :param conversation_id: The conversation ID to use for the chat session
        :param auth_type: The authentication type to use (`google`, `microsoft`, `openai`)
        :param email: The email to use for authentication
        :param password: The password to use for authentication
        :param login_cookies_path: The path to the cookies file to use for authentication
        :param captcha_solver: The captcha solver to use (`pypasser`, `2captcha`)
        :param solver_apikey: The apikey of the captcha solver to use (if any)
        :param proxy: The proxy to use for the browser (`https://ip:port`)
        :param chrome_args: The arguments to pass to the browser
        :param moderation: Whether to enable message moderation
        :param verbose: Whether to enable verbose logging
        """
        self.__init_logger(verbose)

        self.__session_token = session_token
        self.__conversation_id = conversation_id
        self.__auth_type = auth_type
        self.__email = email
        self.__password = password
        self.__login_cookies_path = login_cookies_path
        self.__captcha_solver = captcha_solver
        self.__solver_apikey = solver_apikey
        self.__proxy = proxy
        self.__chrome_args = chrome_args
        self.__moderation = moderation

        if not self.__session_token and (
            not self.__email or not self.__password or not self.__auth_type
        ):
            raise ValueError(
                "Please provide either a session token or login credentials"
            )
        if self.__auth_type not in [None, "google", "microsoft", "openai"]:
            raise ValueError("Invalid authentication type")
        if self.__captcha_solver not in [None, "pypasser", "2captcha"]:
            raise ValueError("Invalid captcha solver")
        if self.__captcha_solver == "2captcha" and not self.__solver_apikey:
            raise ValueError("Please provide a 2captcha apikey")
        if self.__proxy and not re.findall(
            r"(https?|socks(4|5)?):\/\/.+:\d{1,5}", self.__proxy
        ):
            raise ValueError("Invalid proxy format")
        if self.__auth_type == "openai" and self.__captcha_solver == "pypasser":
            try:
                import ffmpeg_downloader as ffdl
            except ModuleNotFoundError:
                raise ValueError(
                    "Please install ffmpeg_downloader, PyPasser, and pocketsphinx by running `pip install ffmpeg_downloader PyPasser pocketsphinx`"
                )

            ffmpeg_installed = bool(ffdl.ffmpeg_version)
            self.logger.debug(f"ffmpeg installed: {ffmpeg_installed}")
            if not ffmpeg_installed:
                import subprocess

                subprocess.run(["ffdl", "install"])
            os.environ["PATH"] += os.pathsep + ffdl.ffmpeg_dir

        self.__init_browser()
        self.__remove_starting_message()
        weakref.finalize(self, self.__del__)

    def __del__(self):
        """
        Close the browser and display
        """
        self.__is_active = False
        if hasattr(self, "driver"):
            self.logger.debug("Closing browser...")
            self.driver.quit()
        if hasattr(self, "display"):
            self.logger.debug("Closing display...")
            self.display.stop()

    def __init_logger(self, verbose: bool) -> None:
        """
        Initialize the logger\n
        :param verbose: Whether to enable verbose logging
        """
        self.logger = logging.getLogger("pyChatGPT")
        self.logger.setLevel(logging.DEBUG)
        if verbose:
            formatter = logging.Formatter("[%(funcName)s] %(message)s")
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            self.logger.addHandler(stream_handler)

    def __init_browser(self) -> None:
        """
        Initialize the browser
        """
        if platform.system() == "Linux" and "DISPLAY" not in os.environ:
            self.logger.debug("Starting virtual display...")
            try:
                from pyvirtualdisplay.display import Display

                self.display = Display()
            except ModuleNotFoundError:
                raise ValueError(
                    "Please install PyVirtualDisplay to start a virtual display by running `pip install PyVirtualDisplay`"
                )
            except FileNotFoundError as e:
                if "No such file or directory: 'Xvfb'" in str(e):
                    raise ValueError(
                        "Please install Xvfb to start a virtual display by running `sudo apt install xvfb`"
                    )
                raise e
            self.display.start()

        self.logger.debug("Initializing browser...")
        options = uc.ChromeOptions()
        options.add_argument("--window-size=1024,768")
        options.set_capability(
            "goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"}
        )
        if self.__proxy:
            options.add_argument(f"--proxy-server={self.__proxy}")
        for arg in self.__chrome_args:
            options.add_argument(arg)
        try:
            self.driver = uc.Chrome(options=options)
        except TypeError as e:
            if str(e) == "expected str, bytes or os.PathLike object, not NoneType":
                raise ValueError("Chrome installation not found")
            raise e

        if self.__login_cookies_path and os.path.exists(self.__login_cookies_path):
            self.logger.debug("Restoring cookies...")
            try:
                with open(self.__login_cookies_path, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                for cookie in cookies:
                    if cookie["name"] == "__Secure-next-auth.session-token":
                        self.__session_token = cookie["value"]
            except json.decoder.JSONDecodeError:
                self.logger.debug(f"Invalid cookies file: {self.__login_cookies_path}")

        if self.__session_token:
            self.logger.debug("Restoring session_token...")
            self.driver.execute_cdp_cmd(
                "Network.setCookie",
                {
                    "domain": "chat.openai.com",
                    "path": "/",
                    "name": "__Secure-next-auth.session-token",
                    "value": self.__session_token,
                    "httpOnly": True,
                    "secure": True,
                },
            )

        if not self.__moderation:
            self.logger.debug("Blocking moderation...")
            self.driver.execute_cdp_cmd(
                "Network.setBlockedURLs",
                {"urls": ["https://chat.openai.com/backend-api/moderations"]},
            )

        self.logger.debug("Ensuring Cloudflare cookies...")
        self.__ensure_cf()

        self.logger.debug("Opening chat page...")
        self.driver.get(f"{chatgpt_chat_url}/{self.__conversation_id}")
        self.__check_blocking_elements()

        self.__is_active = True
        Thread(target=self.__keep_alive, daemon=True).start()

    def __ensure_cf(self, retry: int = 3) -> None:
        """
        Ensure Cloudflare cookies are set\n
        :param retry: Number of retries
        """
        self.logger.debug("Opening new tab...")
        original_window = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab")

        self.logger.debug("Getting Cloudflare challenge...")
        self.driver.get("https://chat.openai.com/api/auth/session")
        try:
            WebDriverWait(self.driver, 10).until_not(
                EC.presence_of_element_located(cf_challenge_form)
            )
        except SeleniumExceptions.TimeoutException:
            self.logger.debug(f"Cloudflare challenge failed, retrying {retry}...")
            self.driver.save_screenshot(f"cf_failed_{retry}.png")
            if retry > 0:
                self.logger.debug("Closing tab...")
                self.driver.close()
                self.driver.switch_to.window(original_window)
                return self.__ensure_cf(retry - 1)
            raise ValueError("Cloudflare challenge failed")
        self.logger.debug("Cloudflare challenge passed")

        self.logger.debug("Validating authorization...")
        response = self.driver.page_source
        if response[0] != "{":
            response = self.driver.find_element(By.TAG_NAME, "pre").text
        response = json.loads(response)
        if (not response) or (
            "error" in response and response["error"] == "RefreshAccessTokenError"
        ):
            self.logger.debug("Authorization is invalid")
            if not self.__auth_type:
                raise ValueError("Invalid session token")
            self.__login()
        self.logger.debug("Authorization is valid")

        self.logger.debug("Closing tab...")
        self.driver.close()
        self.driver.switch_to.window(original_window)

    def __check_capacity(self, target_url: str):
        """
        Check if ChatGPT is at capacity\n
        :param target_url: URL to retry if ChatGPT is at capacity
        """
        while True:
            try:
                self.logger.debug("Checking if ChatGPT is at capacity...")
                WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located(
                        (By.XPATH, '//div[text()="ChatGPT is at capacity right now"]')
                    )
                )
                self.logger.debug("ChatGPT is at capacity, retrying...")
                self.driver.get(target_url)
            except SeleniumExceptions.TimeoutException:
                self.logger.debug("ChatGPT is not at capacity")
                break

    def __login(self) -> None:
        """
        Login to ChatGPT
        """
        self.logger.debug("Opening new tab...")
        original_window = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab")

        self.logger.debug("Opening login page...")
        self.driver.get("https://chat.openai.com/auth/login")
        self.__check_capacity("https://chat.openai.com/auth/login")

        self.logger.debug("Clicking login button...")
        WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable(chatgpt_login_btn)
        ).click()

        WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located(chatgpt_login_h1)
        )

        from . import Auth0

        Auth0.login(self)

        self.logger.debug("Checking if login was successful")
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located(chatgpt_logged_h1)
            )
            if self.__login_cookies_path:
                self.logger.debug("Saving cookies...")
                with open(self.__login_cookies_path, "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            i
                            for i in self.driver.get_cookies()
                            if i["name"] == "__Secure-next-auth.session-token"
                        ],
                        f,
                    )
        except SeleniumExceptions.TimeoutException as e:
            self.driver.save_screenshot("login_failed.png")
            raise e

        self.logger.debug("Closing tab...")
        self.driver.close()
        self.driver.switch_to.window(original_window)

    def __keep_alive(self) -> None:
        """
        Keep the session alive by updating the local storage\n
        Credit to Rawa#8132 in the ChatGPT Hacking Discord server
        """
        while self.__is_active:
            self.logger.debug("Updating session...")
            payload = (
                '{"event":"session","data":{"trigger":"getSession"},"timestamp":%d}'
                % int(time.time())
            )
            try:
                self.driver.execute_script(
                    'window.localStorage.setItem("nextauth.message", arguments[0])',
                    payload,
                )
            except Exception as e:
                self.logger.debug(f"Failed to update session: {str(e)}")
            time.sleep(60)

    def __check_blocking_elements(self) -> None:
        """
        Check for blocking elements and dismiss them
        """
        self.logger.debug("Looking for blocking elements...")
        try:
            intro = WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located(chatgpt_intro)
            )
            self.logger.debug("Dismissing intro...")
            self.driver.execute_script("arguments[0].remove()", intro)
        except SeleniumExceptions.TimeoutException:
            pass

        alerts = self.driver.find_elements(*chatgpt_alert)
        if alerts:
            self.logger.debug("Dismissing alert...")
            self.driver.execute_script("arguments[0].remove()", alerts[0])

    def __stream_message(self):
        prev_content = ""
        while True:
            result_streaming = self.driver.find_elements(*chatgpt_streaming)
            responses = self.driver.find_elements(*chatgpt_big_response)
            if responses:
                response = responses[-1]
                if "text-red" in str(response.get_attribute("class")):
                    self.logger.debug("Response is an error")
                    raise ValueError(response.text)
            response = self.driver.find_elements(*chatgpt_small_response)[-1]
            content = response.text
            if content != prev_content:
                yield content[len(prev_content) :]
                prev_content = content
            if not result_streaming:
                break

    def __click_button(self, xpath: str) -> None:
        """
        Click a button\n
        :param xpath: The xpath of the button to click
        """
        self.logger.debug(f"Clicking button: {xpath}")
        btn = self.driver.find_element(By.XPATH, xpath)
        btn.click()

    def __remove_starting_message(self) -> None:
        WebDriverWait(self.driver, 5)
        if self.__conversation_id:
            xpath = """//*[@id="radix-:ri:"]/div[2]/div[1]/div[2]/button"""
        else:
            xpath = """//*[@id="radix-:re:"]/div[2]/div[1]/div[2]/button"""
        try:
            self.__click_button(xpath)
            self.__click_button(xpath + "[2]")
            self.__click_button(xpath + "[2]")
            self.logger.debug("Starting message removed")
        except SeleniumExceptions.NoSuchElementException:
            self.logger.debug("Starting message not found")

    def send_message(self, message: str, stream: bool = False) -> dict:
        """
        Send a message to ChatGPT\n
        :param message: Message to send
        :return: Dictionary with keys `message` and `conversation_id`
        """
        self.logger.debug("Ensuring Cloudflare cookies...")
        self.__ensure_cf()

        self.logger.debug("Sending message...")
        textbox = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable(chatgpt_textbox)
        )
        textbox.click()
        self.driver.execute_script(
            """
        var element = arguments[0], txt = arguments[1];
        element.value += txt;
        element.dispatchEvent(new Event("change"));
        """,
            textbox,
            message,
        )
        textbox.send_keys(Keys.ENTER)
        textbox.send_keys(Keys.ENTER)
        textbox.send_keys(Keys.BACKSPACE)

        if stream:
            for i in self.__stream_message():
                print(i, end="")
                time.sleep(0.1)
            return {}

        self.logger.debug("Waiting for completion...")
        WebDriverWait(self.driver, 120).until_not(
            EC.presence_of_element_located(chatgpt_streaming)
        )

        self.logger.debug("Getting response...")
        responses = self.driver.find_elements(*chatgpt_big_response)
        if responses:
            response = responses[-1]
            if "text-red" in str(response.get_attribute("class")):
                self.logger.debug("Response is an error")
                raise ValueError(response.text)
        response = self.driver.find_elements(*chatgpt_small_response)
        if len(response) > 0:
            response = response[-1]
            content = markdownify(response.get_attribute("innerHTML")).replace(
                "Copy code`", "`"
            )
        else:
            content = ""

        if not self.__conversation_id:
            conversation_id = ""
            log_entries = self.driver.get_log("performance")
            log_entries = json.loads(json.dumps(log_entries))
            for entry in log_entries:
                entry = json.loads(entry["message"])
                url = entry["message"]["params"].get("request", {}).get("url", "")
                if "https://chat.openai.com/backend-api/conversation/gen_title" in url:
                    conversation_id = url.split("/")[-1]
                    break
            pattern = re.compile(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            )
            matches = pattern.search(self.driver.current_url)
            print(matches)
        else:
            conversation_id = self.__conversation_id
        return {"message": content, "conversation_id": conversation_id}

    def change_conversation(self, conversation_id: str) -> dict:
        if self.__conversation_id == conversation_id:
            self.logger.debug("Already in conversation")
            return {"message": "Already in conversation"}
        self.logger.debug("Changing conversation...")
        try:
            self.driver.get(f"https://chat.openai.com/c/{conversation_id}")
            self.__check_capacity(f"https://chat.openai.com/c/{conversation_id}")
            self.__check_blocking_elements()
            self.__conversation_id = conversation_id
            return {"message": "Changed Successfully"}
        except SeleniumExceptions.NoSuchElementException:
            self.logger.debug("Conversation not found")
            self.driver.save_screenshot("change_conversation_failed.png")
            return {"message": "Conversation not found"}

    def start_new_conversation(self) -> None:
        """
        Start a new conversation
        """
        self.logger.debug("Starting new conversation...")
        self.__conversation_id = ""
        self.driver.get(chatgpt_chat_url)

    def delete_conversation(self) -> None:
        """
        Delete a conversation\n
        """
        if not self.__conversation_id:
            return self.logger.debug("No conversation to delete")
        try:
            delete_button = self.driver.find_element(By.XPATH, "//a/div[2]/button[3]")
            delete_button.click()
            confirmation_button = self.driver.find_element(
                By.XPATH, '//*[@id="radix-:rq:"]/div[2]/div/div/button[1]/div'
            )
            confirmation_button.click()
            self.__conversation_id = ""
            return self.logger.debug("Conversation Deleted")
        except SeleniumExceptions.NoSuchElementException:
            return self.logger.debug("Conversation not Deleted")

    def get_conversation_data(self) -> dict:
        try:
            data_div = self.driver.find_element(
                By.XPATH, '//*[@id="__next"]/div[1]/div[2]/div/main/div[1]/div/div/div'
            )
            reply_elems = data_div.find_elements(By.CSS_SELECTOR, ".markdown")
            reply_elems = [elem.text for elem in reply_elems]
            user_elems = data_div.find_elements(
                By.CSS_SELECTOR, ".flex.flex-grow.flex-col.gap-3"
            )
            user_elems = [
                elem.text for elem in user_elems if elem.text not in reply_elems
            ]
            data = zip(user_elems, reply_elems)
            return dict(data)

        except SeleniumExceptions.NoSuchElementException:
            return {"message": "No conversation found"}

    def refresh_chat_page(self) -> None:
        """
        Refresh the chat page
        """
        if not self.driver.current_url.startswith(chatgpt_chat_url):
            return self.logger.debug("Current URL is not chat page, skipping refresh")

        self.driver.get(chatgpt_chat_url)
        self.__check_capacity(chatgpt_chat_url)
        self.__check_blocking_elements()
