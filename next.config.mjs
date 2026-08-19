/** @type {import('next').NextConfig} */
const nextConfig = {
  // Predicted points change only when ingestion runs, which is once or twice a
  // week. Nothing here should be statically cached at build time.
  experimental: { staleTimes: { dynamic: 0 } },
};

export default nextConfig;
