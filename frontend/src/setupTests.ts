import "@testing-library/jest-dom";

if (typeof window !== "undefined") {
  if (!window.URL.createObjectURL) {
    window.URL.createObjectURL = () =>
      `blob:http://localhost:5173/mock-object-url-${Math.random().toString(36).slice(2)}`;
  }
  if (!window.URL.revokeObjectURL) {
    window.URL.revokeObjectURL = () => {};
  }
}
