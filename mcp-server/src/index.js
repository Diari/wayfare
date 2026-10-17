// Worker entry point. Only the default export is allowed here: Workers treat
// every named export of the main module as an entry point.
import { handle } from "./server.js";

export default {
  fetch(request, env) {
    return handle(request, env);
  },
};
