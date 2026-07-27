import createClient from "openapi-fetch";
import type { paths } from "./v3.gen";

export const studioV3 = createClient<paths>();
