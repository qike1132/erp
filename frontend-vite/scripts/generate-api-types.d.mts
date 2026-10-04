export declare function sanitizeIdent(name: string): string
export declare function buildNameMap(schemaKeys: string[]): Map<string, string>
export declare function tsTypeOf(node: unknown, nameMap: Map<string, string>): string
export declare function generateTypes(spec: unknown): string
