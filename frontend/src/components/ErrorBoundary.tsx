"use client";
import React from "react";

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center min-h-[200px] p-8 text-center rounded-2xl border border-red-500/20 bg-red-500/5">
          <div className="text-red-400 text-lg font-semibold mb-2">Something went wrong</div>
          <div className="text-gray-400 text-sm mb-4 max-w-md">
            {this.state.error?.message ?? "An unexpected error occurred."}
          </div>
          <button
            className="px-4 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 text-red-400 rounded-xl text-sm font-medium transition-colors"
            onClick={() => this.setState({ hasError: false, error: undefined })}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
