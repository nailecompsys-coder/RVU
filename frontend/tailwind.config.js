/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          blue:      "#6FA8DC",
          green:     "#A8D5BA",
          teal:      "#5BC0BE",
          muted:     "#EAF4FF",
          border:    "#E2E8F0",
        },
        ink: {
          DEFAULT:   "#2A3F54",
          secondary: "#6B7C93",
        },
        surface: {
          DEFAULT:   "#FFFFFF",
          soft:      "#F5F7FA",
          muted:     "#EAF4FF",
        },
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #6FA8DC 0%, #A8D5BA 100%)",
        "brand-gradient-v": "linear-gradient(180deg, #EAF4FF 0%, #F8FCFA 100%)",
      },
      fontFamily: {
        sans: [
          "Inter", "SF Pro Display", "-apple-system",
          "BlinkMacSystemFont", "Segoe UI", "sans-serif",
        ],
      },
      borderRadius: {
        "4xl": "2rem",
        "5xl": "2.5rem",
      },
      boxShadow: {
        card:  "0 2px 12px rgba(42,63,84,.07)",
        modal: "0 20px 60px rgba(42,63,84,.18)",
      },
    },
  },
  plugins: [],
};
