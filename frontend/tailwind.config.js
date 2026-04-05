/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#1E5A8D',
        accent: '#6C63FF',
        success: '#38A169',
        warning: '#D69E2E',
        danger: '#E53E3E',
        surface: '#FFFFFF',
        bg: '#F7FAFC',
        'text-primary': '#1A202C',
        'text-secondary': '#4A5568',
        border: '#E2E8F0',
      },
    },
  },
  plugins: [],
}
