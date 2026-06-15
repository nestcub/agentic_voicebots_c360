"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function PlansRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/intelligence/build");
  }, [router]);
  return null;
}
