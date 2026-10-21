import type { ReactNode } from "react";
import { PRODUCT_NAME } from "@/lib/branding";

interface AuthCardProps {
  title: string;
  children: ReactNode;
}

/** Centered card used by the setup and sign-in pages. */
export function AuthCard({ title, children }: AuthCardProps) {
  return (
    <div className="flex min-h-full items-center justify-center bg-bg px-4 py-10">
      <div className="w-full max-w-[400px]">
        <div className="mb-5 flex items-center gap-2 text-[15px] font-semibold text-text">
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
            className="text-accent-text"
          >
            <path d="M4 18L10 6l4 8 2-4 4 8" />
          </svg>
          {PRODUCT_NAME}
        </div>
        <section className="rounded-card border border-border bg-surface p-6 shadow-sm">
          <h1 className="mb-1 text-lg font-semibold text-text">{title}</h1>
          {children}
        </section>
      </div>
    </div>
  );
}
