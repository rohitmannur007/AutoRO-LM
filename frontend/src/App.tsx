import { Route, Routes } from "react-router-dom";
import Shell from "./components/Shell";
import About from "./pages/About";
import Ask from "./pages/Ask";
import Experiments from "./pages/Experiments";
import Extract from "./pages/Extract";
import Overview from "./pages/Overview";
import Settings from "./pages/Settings";
import Sources from "./pages/Sources";
import Synthetic from "./pages/Synthetic";
import Training from "./pages/Training";

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="extract" element={<Extract />} />
        <Route path="ask" element={<Ask />} />
        <Route path="sources" element={<Sources />} />
        <Route path="synthetic" element={<Synthetic />} />
        <Route path="experiments" element={<Experiments />} />
        <Route path="training" element={<Training />} />
        <Route path="settings" element={<Settings />} />
        <Route path="about" element={<About />} />
      </Route>
    </Routes>
  );
}
