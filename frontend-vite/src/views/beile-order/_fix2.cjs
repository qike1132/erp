const fs=require('fs');
const p='d:/erp_system/frontend-vite/src/views/beile-order/BeileOrderTab.vue';
let c=fs.readFileSync(p,'utf8');
const old="watch(listAreaRef, (el) => {\r\n  areaResizeObserver?.disconnect()";
const nw="// bo-list-area 在 v-else 分支内，首次加载（isLoading）时该 DOM 不存在，\r\n// onMounted 无法测量其高度（listAreaHeight 恒为 0 → VirtualList 不渲染）。\r\n// 改为 watch template ref：元素出现后测量高度并挂载 ResizeObserver。\r\nwatch(listAreaRef, (el) => {\r\n  areaResizeObserver?.disconnect()";
if(c.includes(old)){c=c.replace(old,nw);console.log('COMMENT_ADDED')}else{console.log('NOTFOUND')}
fs.writeFileSync(p,c,'utf8');
console.log('DONE');