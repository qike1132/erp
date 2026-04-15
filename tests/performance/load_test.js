import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
    stages: [
        { duration: '30s', target: 50 },  // 模拟在 30s 内上升到 50 虚拟用户
        { duration: '1m', target: 50 },   // 保持 50 用户 1 分钟
        { duration: '30s', target: 100 }, // 升至 100 并发（峰值）
        { duration: '1m', target: 100 },  // 保持峰值
        { duration: '30s', target: 0 },   // 冷却降至 0
    ],
    thresholds: {
        http_req_duration: ['p(99)<500'], // 99% 的请求要在 500ms 内完成
        http_req_failed: ['rate<0.001'],  // 错误率小于 0.1%
    },
};

const BASE_URL = 'http://localhost:5003';
let token = null;

export function setup() {
    // 这里如果系统有鉴权，可以先获取 Token，传给下面执行的函数
    return { };
}

export default function (data) {
    // 1. 测试访问主页或登录页面
    let res = http.get(`${BASE_URL}/login`);
    check(res, {
        'login page status is 200': (r) => r.status === 200,
    });
    
    sleep(1);

    // 2. 测试获取产品列表（模拟日常高频只读请求）
    // 注意：如果有 CSRF 或 Auth，请携带相应的 Header/Cookie
    res = http.get(`${BASE_URL}/product/`);
    check(res, {
        'product list status is 200 or 302': (r) => r.status === 200 || r.status === 302,
    });
    
    sleep(1);
}
