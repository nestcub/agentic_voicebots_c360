"use client";

import { useState } from "react";
import Image from "next/image";
import { ArrowRight, CalendarClock, ClipboardCheck, Eye, EyeOff, Lock, Megaphone, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { HeroWaves } from "@/components/common/HeroWaves";
import { fetchMe, login, setOrganization } from "@/lib/auth";
import { domainConfig } from "@/lib/domainConfig";

// Only what the product actually does today.
const HIGHLIGHTS = [
  { icon: Megaphone, text: "Launch outbound campaigns from a lead list" },
  { icon: CalendarClock, text: "Automatic retries and callbacks" },
  { icon: ClipboardCheck, text: "QA on every completed call" },
];

function BrandPanel() {
  return (
    <aside className="hidden lg:flex flex-col overflow-hidden bg-gradient-to-br from-blue-50 via-indigo-50 to-violet-100">
      {/* self-start: a column flexbox otherwise stretches the logo to the panel's full width. */}
      <Image
        src="/Logo.png"
        alt="Chat360"
        width={170}
        height={40}
        className="self-start h-10 w-auto mx-12 mt-12"
        priority
      />
      <div className="flex-1 flex flex-col justify-center max-w-md space-y-6 px-12 py-10">
        <div className="space-y-2">
          <h2 className="text-3xl font-bold text-foreground">Build. Automate. Scale.</h2>
          <p className="text-muted-foreground">Your AI voice agents, working 24/7.</p>
        </div>
        <ul className="space-y-3">
          {HIGHLIGHTS.map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-center gap-3 text-sm text-foreground">
              <span className="w-9 h-9 shrink-0 rounded-lg bg-card/80 text-primary shadow-sm flex items-center justify-center">
                <Icon className="w-4 h-4" />
              </span>
              {text}
            </li>
          ))}
        </ul>
      </div>
      {/* The waveform gets its own strip below the copy instead of sitting behind it. */}
      <HeroWaves className="shrink-0 h-56 w-full pointer-events-none" centerX={300} />
    </aside>
  );
}

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      // Pre-select the org when there is only one, so the first request needs no choice.
      const me = await fetchMe();
      if (me && me.organizations.length > 0) setOrganization(me.organizations[0].slug);
      window.location.assign("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      setBusy(false);
    }
  }

  function trackCapsLock(e: React.KeyboardEvent<HTMLInputElement>) {
    setCapsLock(e.getModifierState("CapsLock"));
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-background">
      <BrandPanel />

      <main className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm space-y-6">
          {/* Logo only on small screens — the brand panel carries it on desktop. */}
          <Image src="/Logo.png" alt="Chat360" width={136} height={32} className="h-8 w-auto mx-auto lg:hidden" priority />

          <Card className="p-6 sm:p-8 gap-6">
            <div className="space-y-1">
              <h1 className="text-2xl font-semibold text-foreground">Welcome back</h1>
              <p className="text-sm text-muted-foreground">Sign in to {domainConfig.brand}</p>
            </div>

            <form onSubmit={onSubmit} className="space-y-4">
              {error && <ErrorAlert message={error} />}

              <div className="space-y-1.5">
                <Label htmlFor="username">Username</Label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                  <Input
                    id="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    autoFocus
                    required
                    disabled={busy}
                    className="pl-9 h-10"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={trackCapsLock}
                    onKeyUp={trackCapsLock}
                    onBlur={() => setCapsLock(false)}
                    autoComplete="current-password"
                    required
                    disabled={busy}
                    className="pl-9 pr-10 h-10"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground"
                  >
                    {showPassword ? <EyeOff /> : <Eye />}
                  </Button>
                </div>
                {capsLock && <p className="text-xs text-warn">Caps Lock is on</p>}
              </div>

              <Button type="submit" disabled={busy} className="w-full h-10">
                {busy ? <Spinner /> : null}
                {busy ? "Signing in…" : "Sign in"}
                {!busy && <ArrowRight />}
              </Button>
            </form>
          </Card>

          <p className="text-center text-xs text-muted-foreground">Powered by Chat360</p>
        </div>
      </main>
    </div>
  );
}
