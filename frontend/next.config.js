/** @type {import('next').NextConfig} */
const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'
const apiOrigin = apiUrl.replace(/\/api\/v1\/?$/, '')
const wsOrigin = apiOrigin.replace(/^http/, 'ws')
const apiHostname = new URL(apiOrigin).hostname
const apiProtocol = new URL(apiOrigin).protocol.replace(':', '')
const apiPort = new URL(apiOrigin).port
const pendoApiKey = process.env.NEXT_PUBLIC_PENDO_API_KEY?.trim()

// 'wasm-unsafe-eval' lets the self-hosted MediaPipe face landmarker compile its WASM module
const scriptSrc = ["script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'"]
const connectSrc = [`connect-src 'self' ${apiOrigin} ${wsOrigin} ws: wss:`]
const imgSrc = [`img-src 'self' data: blob: ${apiOrigin}`]
const mediaSrc = [`media-src 'self' blob: ${apiOrigin}`]

if (pendoApiKey) {
  scriptSrc.push('https://cdn.pendo.io')
  connectSrc.push('https://*.pendo.io', 'https://*.pendo.com')
  imgSrc.push('https://*.pendo.io', 'https://*.pendo.com')
}

const securityHeaders = [
  { key: 'X-DNS-Prefetch-Control', value: 'on' },
  { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(self), microphone=(self), geolocation=()' },
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      scriptSrc.join(' '),
      "style-src 'self' 'unsafe-inline'",
      connectSrc.join(' '),
      imgSrc.join(' '),
      mediaSrc.join(' '),
      "font-src 'self' data:",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join('; '),
  },
]

const nextConfig = {
  output: 'standalone',
  allowedDevOrigins: ['127.0.0.1'],
  async headers() {
    return [{ source: '/(.*)', headers: securityHeaders }]
  },
  images: {
    remotePatterns: [
      {
        protocol: apiProtocol,
        hostname: apiHostname,
        port: apiPort || undefined,
      },
      {
        protocol: 'http',
        hostname: 'localhost',
      },
    ],
  },
}

module.exports = nextConfig
