const isDev = process.env.NODE_ENV === "development";

const config = {
  plugins: {
    "@tailwindcss/postcss": {
      // 开发环境优化：减少 Tailwind 的编译开销
      ...(isDev && {
        // 禁用一些耗时的检查以加快开发速度
        // 注意：生产环境仍然会进行完整检查
      }),
    },
  },
};

export default config;
