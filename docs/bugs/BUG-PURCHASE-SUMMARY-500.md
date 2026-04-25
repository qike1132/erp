# BUG-PURCHASE-SUMMARY-500 淇璁板綍

- **淇鏃堕棿**: 2026-04-23 08:35:33
- **Git Commit**: 215ee3c246501153bdfaa3313b3e5a71aa03a7c1
- **鏍瑰洜鍒嗘瀽**:
  1. **鐩存帴鍘熷洜**: 绔偣浠ｇ爜 `return {'success': True, **result}` 浣跨敤 `**` 瑙ｅ寘锛屼絾鏈嶅姟鍑芥暟杩斿洖鐨勬槸 `list` 鑰岄潪 `dict`锛屽鑷?`TypeError: 'list' object is not a mapping`锛屽紩鍙?500 閿欒銆?  2. **鏁版嵁缁撴瀯涓嶅尮閰?*: 鏈嶅姟杩斿洖缁撴瀯涓庡墠绔湡鏈涗笉涓€鑷达紙宸ュ巶姹囨€荤己 groups/suppliers/fabrics 宓屽锛屼緵搴斿晢姹囨€荤己 materials 骞抽摵+total_quantity锛?  3. **瀹℃牳杩藉姞鍙戠幇**:
     - P1: product_quantity 瀵规墍鏈?group 閲嶅绱姞鍏ㄩ儴璁㈠崟鏁伴噺锛?725锛?     - P2: 渚涘簲鍟嗘眹鎬?key 鏈寘鍚?unit锛屼笉鍚屽崟浣嶇墿鏂欒閿欒鍚堝苟锛?760-768锛?     - P2: float 绱姞绮惧害婕傜Щ锛?769锛?- **褰卞搷鑼冨洿**: 閲囪喘涓績姹囨€讳笅鍗曞姛鑳藉畬鍏ㄤ笉鍙敤
- **淇鏂规**:
  - 閲嶆瀯 `get_factory_order_summary` 杩斿洖 dict锛屽祵濂?groups->suppliers->fabrics 缁撴瀯
  - 閲嶆瀯 `get_supplier_order_summary` 杩斿洖 dict锛屽钩閾?materials 鍒楄〃
  - 淇 product_quantity锛氭瘡涓?group 浠呮眹鎬诲叾鍏宠仈璁㈠崟鐨勬暟閲忥紙閫氳繃 order_ids set 杩借釜锛?  - 淇渚涘簲鍟嗘眹鎬伙細灏?unit 绾冲叆鑱氬悎 key锛屼笉鍚屽崟浣嶇墿鏂欏垎鍒緭鍑?  - 淇绮惧害锛氫娇鐢?Decimal 绱姞鏇夸唬 float
- **淇鏂囦欢**: `fastapi_app/services/purchase_center_service.py`:673-779
- **楠岃瘉缁撴灉**: L1~L5 鍏ㄩ儴閫氳繃
  - 76 pytest passed, 0 failed
  - bandit: 0 issues
  - P1-01/P2-01/P2-02 鍐呰仈娴嬭瘯鍏ㄩ儴閫氳繃
- **鍋ュ悍绔偣**: http://localhost:5002/health
