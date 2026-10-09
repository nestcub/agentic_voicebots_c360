import { CircleAlert } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";

export function ErrorAlert({ message, action }: { message: string; action?: React.ReactNode }) {
  return (
    <Alert variant="destructive" className="border-bad/30 bg-bad/5">
      <CircleAlert />
      <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
        <span>{message}</span>
        {action}
      </AlertDescription>
    </Alert>
  );
}
