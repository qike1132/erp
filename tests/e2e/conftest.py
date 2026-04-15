"""
E2E测试配置
"""
import pytest
from selenium import webdriver


def pytest_addoption(parser):
    """添加E2E测试命令行选项"""
    parser.addoption(
        '--e2e',
        action='store_true',
        default=False,
        help='运行端到端测试'
    )


def pytest_configure(config):
    """配置E2E测试标记"""
    config.addinivalue_line(
        'markers', 'e2e: 端到端测试标记'
    )


def pytest_collection_modifyitems(config, items):
    """根据命令行选项过滤测试"""
    if not config.getoption('--e2e'):
        skip_e2e = pytest.mark.skip(reason='需要--e2e选项来运行E2E测试')
        for item in items:
            if 'e2e' in item.keywords:
                item.add_marker(skip_e2e)


@pytest.fixture(scope='session')
def e2e_base_url():
    """E2E测试基础URL"""
    return 'http://localhost:5000'


@pytest.fixture(scope='session')
def browser():
    """浏览器驱动fixture"""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(10)
    
    yield driver
    
    driver.quit()
