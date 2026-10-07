import { User, UserManager } from "oidc-client-ts";
import { type ReactNode, useEffect, useState } from "react";

import { setTokenSource } from "../api/client";
import { config } from "../config";
import { AuthContext } from "./context";

const CALLBACK_PATH = "/auth/callback";

const userManager = new UserManager({
  authority: config.oidcAuthority,
  client_id: config.oidcClientId,
  redirect_uri: `${window.location.origin}${CALLBACK_PATH}`,
  post_logout_redirect_uri: window.location.origin,
  response_type: "code",
  scope: "openid profile email",
  automaticSilentRenew: true,
});

let currentUser: User | null = null;
setTokenSource(() => currentUser?.access_token);

// Started once per page load. The authorization code in the callback URL is single-use,
// so this must not run again when React re-runs effects in development.
let startup: Promise<User | null> | undefined;

function signIn(): Promise<User | null> {
  startup ??= (async () => {
    if (window.location.pathname === CALLBACK_PATH) {
      const user = await userManager.signinRedirectCallback();
      window.history.replaceState({}, "", "/");
      return user;
    }
    const user = await userManager.getUser();
    if (user && !user.expired) return user;
    await userManager.signinRedirect();
    return null;
  })();
  return startup;
}

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "authenticated"; user: User };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    const accept = (user: User) => {
      currentUser = user;
      setState({ status: "authenticated", user });
    };
    signIn().then(
      (user) => user && accept(user),
      (error: unknown) =>
        setState({ status: "error", message: error instanceof Error ? error.message : "unknown" }),
    );
    // Fires after each silent token renewal.
    userManager.events.addUserLoaded(accept);
    return () => userManager.events.removeUserLoaded(accept);
  }, []);

  if (state.status === "loading") {
    return <p className="p-8 text-slate-500">Signing in…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-8">
        <p className="text-red-700">Sign-in failed: {state.message}</p>
        <button className="mt-4 underline" onClick={() => void userManager.signinRedirect()}>
          Try again
        </button>
      </div>
    );
  }
  return (
    <AuthContext.Provider
      value={{
        name: state.user.profile.name ?? state.user.profile.email ?? "",
        signOut: () => void userManager.signoutRedirect(),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
