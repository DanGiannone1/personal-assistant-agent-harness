import type { NextConfig } from "next";
import path from "node:path";

const nextDistDir = process.env.NEXT_DIST_DIR;

const nextConfig: NextConfig = {
  ...(nextDistDir
    ? {
        distDir: nextDistDir,
        typescript: { tsconfigPath: `${nextDistDir}.tsconfig.json` },
      }
    : {}),
  output: "standalone",
  turbopack: {
    // The frontend is its own Node project; the repository root also has a lockfile.
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
