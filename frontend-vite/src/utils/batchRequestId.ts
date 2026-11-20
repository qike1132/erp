/**
 * 批量提交的每行幂等令牌工厂。
 *
 * 同一次提交的所有行共享一个批次随机段，行下标区分；网络层重试复用同一 body
 * 时令牌不变，后端 `inventory_log.idem_key` 可去重。用户重新发起提交会生成
 * 新的批次段，不会误杀合法的新操作。
 */
let _sequence = 0

export function createBatchRequestId(prefix: string): (index: number) => string {
  _sequence += 1
  const seed = [
    Date.now().toString(36),
    _sequence.toString(36),
    Math.random().toString(36).slice(2, 10),
  ].join('-')
  return (index: number) => `${prefix}:${seed}:${index}`
}
