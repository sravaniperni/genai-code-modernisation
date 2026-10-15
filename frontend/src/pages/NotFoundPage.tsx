import { Link } from 'react-router';
import { PageHeader } from '../components/PageHeader';
import { useDocumentTitle } from '../hooks/useDocumentTitle';

export function NotFoundPage() {
  useDocumentTitle('Not found');
  return (
    <>
      <PageHeader title="Page not found" />
      <p>
        There is nothing at this address. Go to the <Link to="/">dashboard</Link>.
      </p>
    </>
  );
}
