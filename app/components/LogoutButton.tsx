"use client";

import { useRouter } from "next/navigation";
import { postJson } from "./client-utils";

export default function LogoutButton({ label }: { label: string }) {
  const router = useRouter();
  return (
    <button
      className="btn btn-ghost btn-sm"
      onClick={async () => {
        await postJson("/api/auth/logout");
        router.push("/");
        router.refresh();
      }}
    >
      {label}
    </button>
  );
}
