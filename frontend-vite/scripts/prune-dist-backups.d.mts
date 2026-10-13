export declare function parseStamp(name: string): string | null
export declare function selectBackupsToDrop(
  candidates: string[],
  opts: { days: number; now?: Date },
): { drop: string[]; cutoffDay: string }
