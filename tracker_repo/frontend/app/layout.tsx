import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'TWVS Community Request Tracker',
  description: 'Song request heart-count tracker for Tim Welch Vocal Studio patrons',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
