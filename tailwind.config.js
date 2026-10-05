export default {
  content: ['./index.html', './src/**/*.{ts,tsx,html}'],
  theme: {
    extend: {
      colors: {
        krypt: {
          black: '#000000',
          void: '#0A0A0F',
          surface: '#11111A',
          surface2: '#171722',
          border: 'rgba(255,255,255,0.08)',
          borderHi: 'rgba(255,255,255,0.16)',
          muted: '#A1A1AA',
          dim: '#71717A',
          indigo: '#6366F1',
          purple: '#A855F7',
          pink: '#EC4899',
          win: '#22C55E',
          loss: '#EF4444',
          warn: '#F59E0B',
        },
      },
      fontFamily: {
        sans: ['"Chakra Petch"', 'Inter', 'system-ui', 'sans-serif'],
        pixel: ['"Press Start 2P"', 'monospace'],
        mono: ['"JetBrains Mono"', 'Menlo', 'monospace'],
      },
      backgroundImage: {
        'krypt-glow':
          'linear-gradient(90deg, #6366F1 0%, #A855F7 50%, #EC4899 100%)',
        'krypt-radial':
          'radial-gradient(700px circle at 15% 0%, rgba(168,85,247,0.14), transparent 60%)',
        'krypt-radial-r':
          'radial-gradient(600px circle at 90% 0%, rgba(236,72,153,0.10), transparent 60%)',
      },
      boxShadow: {
        'krypt-glow': '0 0 28px 0 rgba(168,85,247,0.35)',
        'krypt-soft': '0 10px 40px -10px rgba(168,85,247,0.20)',
        'krypt-strong': '0 0 60px -10px rgba(168,85,247,0.55)',
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'gradient-x': {
          '0%,100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
        'pulse-slow': {
          '0%,100%': { opacity: '0.4' },
          '50%': { opacity: '0.9' },
        },
      },
      animation: {
        'fade-in': 'fade-in 280ms ease-out',
        'gradient-x': 'gradient-x 6s ease infinite',
        'pulse-slow': 'pulse-slow 2.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
