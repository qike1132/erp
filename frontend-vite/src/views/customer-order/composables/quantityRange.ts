/**
 * 数量范围校验（客户订单页的统一导入入口）。
 *
 * 真相源已上移到 @/utils/quantity（客户订单页与共享 components/ocr 粘贴识别
 * 共用同一组常量）。本文件只做再导出，保住页内既有导入的稳定路径，
 * 勿在此新增定义。
 */
export {
  QUANTITY_MIN,
  QUANTITY_MAX,
  QUANTITY_MAX_TEXT,
  QUANTITY_RANGE_MESSAGE,
  isQuantityOutOfRange,
  quantityAriaInvalid,
} from '@/utils/quantity'
