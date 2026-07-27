import { render } from "preact";
import { App } from "./app";
import "./styles.css";

document.title = "Studio v3";
const root = document.getElementById("app");
if (root) render(<App />, root);
