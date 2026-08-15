const fs=require('fs');
const p='d:/erp_system/frontend-vite/src/views/beile-order/BeileOrderTab.vue';
let c=fs.readFileSync(p,'utf8');
c=c.replace('const PAGE_SIZE_OPTIONS = [18, 30, 50, 100] // test','const PAGE_SIZE_OPTIONS = [18, 30, 50, 100]');
c=c.replace("import { reactive, computed, ref, watch, onMounted, onUnmounted } from 'vue'","import { reactive, computed, ref, watch, onUnmounted } from 'vue'");
const old="onMounted(() => {\r\n  measureListArea()\r\n  if (listAreaRef.value && typeof ResizeObserver !== 'undefined') {\r\n    areaResizeObserver = new ResizeObserver(measureListArea)\r\n    areaResizeObserver.observe(listAreaRef.value)\r\n  }\r\n})";
const nw="watch(listAreaRef, (el) => {\r\n  areaResizeObserver?.disconnect()\r\n  areaResizeObserver = null\r\n  if (!el) return\r\n  measureListArea()\r\n  if (typeof ResizeObserver !== 'undefined') {\r\n    areaResizeObserver = new ResizeObserver(measureListArea)\r\n    areaResizeObserver.observe(el)\r\n  }\r\n}, { flush: 'post' })";
if(c.includes(old)){c=c.replace(old,nw);console.log('REPLACED')}else{console.log('NOTFOUND')}
fs.writeFileSync(p,c,'utf8');
console.log('DONE');
