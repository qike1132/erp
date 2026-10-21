export declare function readBuster(source: string): string | null
export declare function computeHash(source: string): string
export declare function evaluate(input: {
  currentBuster: string | null
  currentHash: string
  snapshot: { buster: string; apiTypesSha256: string }
}): { ok: boolean; errors: string[] }
export declare function evaluateUpdate(input: {
  currentBuster: string | null
  currentHash: string
  snapshot: { buster: string; apiTypesSha256: string }
}): { ok: boolean; errors: string[] }
