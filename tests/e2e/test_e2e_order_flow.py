"""
端到端测试 - 订单完整流程
使用Selenium进行浏览器自动化测试
"""
import pytest
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import TimeoutException


@pytest.mark.e2e
class TestE2EOrderFlow:
    """端到端订单流程测试"""
    
    @pytest.fixture(scope='class')
    def driver(self):
        """初始化浏览器驱动"""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(10)
        driver.set_window_size(1920, 1080)
        
        yield driver
        
        driver.quit()
    
    @pytest.fixture(scope='class')
    def base_url(self, app):
        """获取测试服务器URL"""
        return 'http://localhost:5000'
    
    def test_login_flow(self, driver, base_url):
        """测试登录流程"""
        driver.get(f'{base_url}/login')
        
        username_input = driver.find_element(By.NAME, 'username')
        password_input = driver.find_element(By.NAME, 'password')
        login_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        
        username_input.send_keys('admin')
        password_input.send_keys('admin123')
        login_button.click()
        
        WebDriverWait(driver, 10).until(
            EC.url_contains('/dashboard')
        )
        
        assert 'dashboard' in driver.current_url
    
    def test_product_search_flow(self, driver, base_url):
        """测试产品搜索流程"""
        self.test_login_flow(driver, base_url)
        
        driver.get(f'{base_url}/products')
        
        search_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'search'))
        )
        search_input.send_keys('测试产品')
        search_input.submit()
        
        product_list = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'product-list'))
        )
        
        assert product_list is not None
    
    def test_create_order_flow(self, driver, base_url):
        """测试创建订单完整流程"""
        self.test_login_flow(driver, base_url)
        
        driver.get(f'{base_url}/orders/new')
        
        product_select = Select(WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'product_id'))
        ))
        product_select.select_by_index(1)
        
        quantity_input = driver.find_element(By.NAME, 'quantity')
        quantity_input.clear()
        quantity_input.send_keys('10')
        
        submit_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        submit_button.click()
        
        WebDriverWait(driver, 10).until(
            EC.url_contains('/orders')
        )
        
        success_message = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'alert-success'))
        )
        
        assert success_message is not None
    
    def test_stock_management_flow(self, driver, base_url):
        """测试库存管理流程"""
        self.test_login_flow(driver, base_url)
        
        driver.get(f'{base_url}/stock/in')
        
        product_select = Select(WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, 'product_id'))
        ))
        product_select.select_by_index(1)
        
        quantity_input = driver.find_element(By.NAME, 'quantity')
        quantity_input.clear()
        quantity_input.send_keys('100')
        
        submit_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        submit_button.click()
        
        WebDriverWait(driver, 10).until(
            EC.url_contains('/stock')
        )
        
        assert 'stock' in driver.current_url
    
    def test_approval_workflow(self, driver, base_url):
        """测试审批工作流"""
        self.test_login_flow(driver, base_url)
        
        driver.get(f'{base_url}/approvals')
        
        approval_list = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'approval-list'))
        )
        
        approve_buttons = driver.find_elements(By.CLASS_NAME, 'approve-btn')
        if approve_buttons:
            approve_buttons[0].click()
            
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, 'alert-success'))
            )


@pytest.mark.e2e
class TestE2EUserExperience:
    """用户体验端到端测试"""
    
    @pytest.fixture(scope='class')
    def driver(self):
        """初始化浏览器驱动"""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        
        driver = webdriver.Chrome(options=options)
        driver.implicitly_wait(10)
        driver.set_window_size(1920, 1080)
        
        yield driver
        
        driver.quit()
    
    def test_page_load_performance(self, driver, base_url):
        """测试页面加载性能"""
        start_time = time.time()
        driver.get(f'{base_url}/login')
        load_time = time.time() - start_time
        
        assert load_time < 2.0, f'页面加载时间过长: {load_time}秒'
    
    def test_responsive_design(self, driver, base_url):
        """测试响应式设计"""
        sizes = [
            (1920, 1080),
            (1366, 768),
            (768, 1024),
            (375, 667)
        ]
        
        for width, height in sizes:
            driver.set_window_size(width, height)
            driver.get(f'{base_url}/login')
            
            login_form = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, 'form'))
            )
            
            assert login_form.is_displayed()
    
    def test_error_handling(self, driver, base_url):
        """测试错误处理"""
        driver.get(f'{base_url}/login')
        
        username_input = driver.find_element(By.NAME, 'username')
        password_input = driver.find_element(By.NAME, 'password')
        login_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        
        username_input.send_keys('wronguser')
        password_input.send_keys('wrongpass')
        login_button.click()
        
        error_message = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'alert-danger'))
        )
        
        assert error_message.is_displayed()
