/**
 * Root page - redirects to dashboard
 */

import { redirect } from 'next/navigation';

export default function Home() {
  // Redirect to the main dashboard
  redirect('/dashboard');
}
