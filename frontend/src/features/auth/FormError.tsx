interface FormErrorProps {
  message: string | null;
}

export function FormError({ message }: FormErrorProps) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded border border-danger px-3 py-2 text-sm text-danger">
      {message}
    </p>
  );
}
