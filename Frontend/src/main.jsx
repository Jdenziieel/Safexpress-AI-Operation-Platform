import { createRoot } from "react-dom/client";
import "./index.css";
// Gemini-clean SweetAlert overrides — must load AFTER index.css so the
// default Swal styles injected by sweetalert2 at runtime are overridden
// by our higher-specificity rules. Touching this import order will
// regress every modal across the app.
import "./css/swal-overrides.css";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <App />
);
