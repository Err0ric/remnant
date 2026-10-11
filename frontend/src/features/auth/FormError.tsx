interface FormErrorProps {
  message: string | null;
}

export function FormError({ message }: FormErrorProps) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="rounded border border-danger bg-sev-critical-bg px-3 py-2 text-sm text-sev-critical-text"
    >
      {message}
    </p>
  );
}
