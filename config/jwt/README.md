# JWT 密钥目录

此目录仅存放 **公钥**（`public.pem`），公钥可公开。

**私钥（`private.pem`）严禁提交到代码仓库。** 生产环境通过以下方式注入：

## K8s 部署
```yaml
volumes:
  - name: jwt-secret
    secret:
      secretName: erp-jwt-keys
volumeMounts:
  - name: jwt-secret
    mountPath: /run/secrets
    readOnly: true
```
环境变量：`JWT_PRIVATE_KEY_PATH=/run/secrets/private.pem`

## Docker 部署
```bash
docker run -v /host/path/private.pem:/run/secrets/private.pem:ro \
  -e JWT_PRIVATE_KEY_PATH=/run/secrets/private.pem ...
```

## 生成新密钥对
```bash
openssl genpkey -algorithm RSA -out private.pem -pkeyopt rsa_keygen_bits:4096
openssl rsa -pubout -in private.pem -out public.pem
# private.pem 保管在 Secret 管理系统；public.pem 提交到此目录
```

## 密钥轮换
1. 生成新密钥对
2. 先部署新公钥（verifier 优先，接受新旧两种 token）
3. 再切换签名者使用新私钥
4. 观察 token 验证成功率，确认无异常后下线旧公钥
