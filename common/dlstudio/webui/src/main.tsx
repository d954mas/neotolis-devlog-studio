import { render } from "preact";
import { App } from "./app";
import { ResearchApp } from "./components/research/ResearchApp";
import "./styles.css";

const root = document.getElementById("app");
const isResearch = window.location.pathname.startsWith("/research");
document.body.classList.toggle("research-page", isResearch);
document.title = isResearch ? "Pattern Lab · Studio" : "Studio v2";
if (root) render(isResearch ? <ResearchApp /> : <App />, root);
