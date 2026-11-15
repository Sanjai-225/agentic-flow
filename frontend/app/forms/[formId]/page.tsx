'use client';

/* Public hosted form (Form Submission Trigger). Deliberately NOT wrapped in RequireAuth. */

import { PublicFormView } from '@/components/PublicFormView';

export default function PublicFormPage({ params }: { params: { formId: string } }) {
  return <PublicFormView formId={params.formId} />;
}
