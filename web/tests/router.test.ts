// LOCAL MOCK test (jsdom): the router guard must not auto-start sign-in.
import { describe, expect, it, vi } from "vitest";
import { router } from "../src/router";

describe("router guard", () => {
  it("sends a signed-out visitor to the login screen without calling the identity provider", async () => {
    const fetchSpy = vi.fn(); vi.stubGlobal("fetch", fetchSpy);
    await router.push("/chat/abc"); await router.isReady();
    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.next).toBe("/chat/abc");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
  it("shows the login screen at the root as well", async () => {
    await router.push("/"); expect(router.currentRoute.value.path).toBe("/login");
  });
});
