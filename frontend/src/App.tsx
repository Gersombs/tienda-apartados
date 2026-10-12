import { Toaster } from '@/components/ui/toaster';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Index from './pages/Index';
import Catalogo from './pages/Catalogo';
import Producto from './pages/Producto';
import Apartado from './pages/Apartado';
import Confirmacion from './pages/Confirmacion';
import Contenido from './pages/Contenido';
import Admin from './pages/Admin';
import NotFound from './pages/NotFound';

const App = () => (
  <>
    <Toaster />
    <BrowserRouter>
      <Routes>
          <Route path="/" element={<Index />} />
          <Route path="/catalogo" element={<Catalogo />} />
          <Route path="/categoria/:slug" element={<Catalogo />} />
          <Route path="/producto/:slug" element={<Producto />} />
          <Route path="/apartado" element={<Apartado />} />
          <Route path="/confirmacion" element={<Confirmacion />} />
          <Route path="/como-funciona" element={<Contenido contentKey="how_it_works" />} />
          <Route path="/preguntas-frecuentes" element={<Contenido contentKey="faq_content" />} />
          <Route path="/aviso-de-privacidad" element={<Contenido contentKey="privacy_policy" />} />
          <Route
            path="/politicas-de-apartado"
            element={<Contenido contentKey="reservation_policy" />}
          />
          <Route path="/admin" element={<Admin />} />
          <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  </>
);

export default App;
