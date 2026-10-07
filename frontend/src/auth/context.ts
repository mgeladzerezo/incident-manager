import { createContext, useContext } from "react";

export interface AuthSession {
  name: string;
  signOut: () => void;
}

export const AuthContext = createContext<AuthSession | null>(null);

export function useAuth(): AuthSession {
  const session = useContext(AuthContext);
  if (session === null) throw new Error("useAuth must be used inside AuthProvider");
  return session;
}
