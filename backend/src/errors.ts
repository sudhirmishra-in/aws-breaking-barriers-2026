export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public retryable = false) {
    super(message);
  }
}
export const unauthorized = () => new ApiError(401, "unauthorized", "Sign in required.");
export const forbidden = (m = "Not allowed.") => new ApiError(403, "forbidden", m);
export const notFound = () => new ApiError(404, "not_found", "Not found.");
export const conflict = (code: string, m: string, retryable = false) => new ApiError(409, code, m, retryable);
export const invalid = (m: string) => new ApiError(400, "validation_error", m);
