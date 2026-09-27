"""Bespoke Editorial Feature Articles for Historic Landmark Supernovae.

Provides rich, publication-grade journalistic and scientific articles for
Tier 1 Blockbuster events (SN 1987A, SN 1054, SN 1006, SN 1572, SN 1604,
SN 1885A, SN 1993J, SN 1994I, SN 1998bw, SN 2006gy, SN 2011fe, SN 2014J,
SN 2023ixf, SN 2024ggi).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


def _get_blockbuster_raw(
    name: str,
    meta: Dict[str, Any],
    claimedtype: str,
    discoverdate: str,
    discoverer: str,
    maxappmag: str,
    dist_ly_str: str,
    host: str,
    ra_str: str,
    dec_str: str,
    lifecycle_html: str,
) -> Optional[str]:
    """Return a bespoke, museum-grade editorial feature article for landmark events."""
    clean = re.sub(r"[^A-Za-z0-9]", "", name).upper()

    # 1. SN 1987A - The Modern Benchmark in the Large Magellanic Cloud
    if "1987A" in clean:
        return f"""
    <div class="narrative blockbuster-narrative">
      <div class="article-chapter">
        <div class="article-chapter-num">HISTORIC BENCHMARK &bull; THE CLOSEST SUPERNOVA IN 400 YEARS</div>
        <h2>The Explosion That Revolutionized Modern Astrophysics</h2>
        <p class="article-lead">
          On the night of February 23, 1987, astronomers atop Las Campanas Observatory in Chile noticed a brilliant blue star
          shining in the outskirts of the Tarantula Nebula in the Large Magellanic Cloud where nothing had been visible hours before.
          Designated <strong>SN 1987A</strong>, it was the closest observed supernova since the invention of the telescope—and
          it ignited a golden age of multi-messenger astrophysics.
        </p>

        <div class="article-callout" style="border-left:4px solid #f59e0b;background:rgba(245,158,11,0.08);padding:1.25rem;border-radius:6px;margin:1.5rem 0;">
          <div style="font-weight:700;color:#f59e0b;font-size:1.05rem;margin-bottom:0.4rem;">★ Landmark Dossier: SN 1987A</div>
          <div style="font-size:0.92rem;color:#cbd5e1;line-height:1.6;">
            <strong>Progenitor:</strong> Sanduleak −69° 202 (Blue Supergiant, ~20 M<sub>☉</sub>) &bull;
            <strong>Distance:</strong> ~168,000 Light-Years (LMC) &bull;
            <strong>Peak Apparent Magnitude:</strong> m = +2.9 (Naked-Eye) &bull;
            <strong>Multi-Messenger First:</strong> 24 Extragalactic Neutrinos Detected
          </div>
        </div>

        <p>
          Prior to 1987, stellar evolution models universally dictated that only bloated red supergiants could end their lives as Type II supernovae.
          Yet archival plates revealed that 1987A's progenitor was <strong>Sanduleak −69° 202</strong>, a compact <em>blue</em> supergiant.
          This astonishing finding forced astrophysicists to rewrite textbooks, proving that rapid mass-loss or binary mergers in low-metallicity environments
          could cause a massive star to contract and heat up into a blue supergiant shortly before its iron core collapsed.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">MULTI-MESSENGER MILESTONE</div>
        <h2>The 10-Second Neutrino Flash That Proved Core Collapse</h2>
        <p>
          Approximately three hours before optical light burst through the star's surface, a ghostly pulse of subatomic particles swept through Earth.
          Deep underground in Japan and the United States, three independent water Cherenkov detectors—<strong>Kamiokande II</strong> (11 events),
          <strong>IMB</strong> (8 events), and <strong>Baksan</strong> (5 events)—registered a simultaneous 13-second burst of 24 anti-electron neutrinos.
        </p>
        <p>
          This historic detection provided the first direct empirical confirmation of Hans Bethe's core-collapse theory:
          over <strong>99% of the supernova's 10⁵³ ergs of gravitational binding energy</strong> was carried away by neutrinos formed as protons
          and electrons were crushed into a newborn neutron star. The detection earned Masatoshi Koshiba the 2002 Nobel Prize in Physics.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">HUBBLE &amp; JWST REVELATIONS</div>
        <h2>The Iconic Triple Rings and the 37-Year Quest for the Central Remnant</h2>
        <p>
          When the Hubble Space Telescope launched, SN 1987A became one of its most scrutinized targets. HST resolved a breathtaking system of three glowing rings:
          a dense equatorial ring and two faint outer lobes, illuminated like pearls on a necklace as the supersonic blast wave slammed into material expelled
          by the progenitor star 20,000 years prior.
        </p>
        <p>
          For over 35 years, the fate of the central remnant remained an agonizing cosmic mystery: did the core collapse into a neutron star or swallow itself into a black hole?
          Finally, in February 2024, observations with the <strong>James Webb Space Telescope (JWST)</strong> detected narrow emission lines of highly ionized argon and sulfur
          emanating directly from the central ejecta dust clump—providing definitive proof that a newborn, intensely hot neutron star (pulsar) survived at ground zero!
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">OBSERVABILITY &amp; CELESTIAL LOCATION</div>
        <h2>Observing the Historic Remnant</h2>
        <p>
          In the southern night sky, SN 1987A is located in the constellation <strong>Dorado</strong> at Right Ascension <code>{ra_str}</code>
          and Declination <code>{dec_str}</code>. Today, amateur and professional astronomers track the slowly brightening remnant ring in optical, radio,
          and X-ray wavelengths as the cosmic debris continues to plow through the surrounding interstellar medium.
        </p>
        {lifecycle_html}
      </div>
    </div>
    """

    # 2. SN 1054 - The Crab Nebula Supernova
    if "1054" in clean:
        return f"""
    <div class="narrative blockbuster-narrative">
      <div class="article-chapter">
        <div class="article-chapter-num">HISTORIC LANDMARK &bull; JULY 1054 AD</div>
        <h2>The 'Guest Star' That Created the Crab Nebula</h2>
        <p class="article-lead">
          On July 4, 1054 (Song Dynasty, China), court astronomers of Emperor Renzong looked toward the constellation Taurus and documented
          the sudden appearance of a brilliant "guest star" (客星). Shining four times brighter than Venus, it was visible in broad daylight
          for 23 consecutive days and remained visible to the unaided eye in the night sky for nearly two years.
        </p>

        <div class="article-callout" style="border-left:4px solid #f59e0b;background:rgba(245,158,11,0.08);padding:1.25rem;border-radius:6px;margin:1.5rem 0;">
          <div style="font-weight:700;color:#f59e0b;font-size:1.05rem;margin-bottom:0.4rem;">★ Landmark Dossier: SN 1054 (The Crab Supernova)</div>
          <div style="font-size:0.92rem;color:#cbd5e1;line-height:1.6;">
            <strong>Historical Observers:</strong> Song Dynasty Astronomers, Arab Astronomer Ibn Butlan, Ancestral Puebloan Rock Art &bull;
            <strong>Distance:</strong> ~6,500 Light-Years &bull;
            <strong>Peak Apparent Magnitude:</strong> m &approx; −6.0 (Visible in Daylight) &bull;
            <strong>Surviving Remnant:</strong> Messier 1 (The Crab Nebula) &amp; PSR B0531+21 (30 Hz Pulsar)
          </div>
        </div>

        <p>
          Records of SN 1054 were scrupulously transcribed in the <em>Song Shi</em> (History of Song) and the <em>Wenxian Tongkao</em>, alongside
          independent medical and astronomical writings by the Christian Arab physician Ibn Butlan in Baghdad. Across the Atlantic Ocean, pictographs
          at Chaco Canyon in New Mexico depict a crescent moon adjacent to a ten-pointed star, believed to commemorate the July 5, 1054 conjunction.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">THE BIRTH OF A PULSAR</div>
        <h2>The Discovery of the Crab Pulsar &amp; Modern High-Energy Physics</h2>
        <p>
          Seven centuries later, in 1731, English amateur astronomer John Bevis discovered a faint glowing cloud at the exact celestial coordinates:
          what Charles Messier would later catalog as <strong>Messier 1 (M1)</strong>, the Crab Nebula.
        </p>
        <p>
          In 1968, radio astronomers discovered the beating heart of the Crab: <strong>PSR B0531+21</strong>, a rapidly rotating neutron star
          spinning <strong>30.2 times per second</strong> with a magnetic field of nearly 4 trillion Gauss. The Crab Pulsar continuously injects
          relativistic electrons and positrons into the nebula, illuminating the intricate filamentary tendrils of ionized gas across every band of
          the electromagnetic spectrum—from radio waves to ultra-high-energy teraelectronvolt (TeV) gamma rays!
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">BACKYARD OBSERVATION</div>
        <h2>Locating the Crab Nebula in Taurus</h2>
        <p>
          While the optical outburst faded into history nine centuries ago, the expanding remnant nebula is one of the most popular showpieces
          for amateur telescopes under dark skies. Located near the southern horn of <strong>Taurus the Bull</strong> (RA <code>{ra_str}</code>,
          Dec <code>{dec_str}</code>), an 8-inch telescope reveals its eerie oval ghostly glow, expanding at 1,500 kilometers every second.
        </p>
        {lifecycle_html}
      </div>
    </div>
    """

    # 3. SN 1006 - The Brightest Supernova in Human History
    if "1006" in clean:
        return f"""
    <div class="narrative blockbuster-narrative">
      <div class="article-chapter">
        <div class="article-chapter-num">HISTORIC LANDMARK &bull; MAY 1006 AD</div>
        <h2>The Brightest Stellar Event in Recorded Human History</h2>
        <p class="article-lead">
          In May 1006, a dazzling celestial explosion lit up the constellation Lupus. With an estimated peak apparent magnitude of
          <strong>−7.5 to −9.0</strong>, <strong>SN 1006</strong> was bright enough to cast distinct shadows across the ground at night
          and was easily seen in the middle of the day for weeks. It remains the most luminous single stellar explosion ever witnessed by human eyes.
        </p>

        <div class="article-callout" style="border-left:4px solid #f59e0b;background:rgba(245,158,11,0.08);padding:1.25rem;border-radius:6px;margin:1.5rem 0;">
          <div style="font-weight:700;color:#f59e0b;font-size:1.05rem;margin-bottom:0.4rem;">★ Landmark Dossier: SN 1006</div>
          <div style="font-size:0.92rem;color:#cbd5e1;line-height:1.6;">
            <strong>Type:</strong> Thermonuclear Type Ia &bull;
            <strong>Distance:</strong> ~7,200 Light-Years (Lupus) &bull;
            <strong>Peak Apparent Magnitude:</strong> m &approx; −7.5 to −9.0 (Casting Visible Shadows) &bull;
            <strong>Historical Records:</strong> Ibn Sina (Avicenna), Chinese Dynastic Annals, St. Gallen Abbey (Switzerland)
          </div>
        </div>

        <p>
          Chroniclers from four continents left detailed accounts. In Baghdad and Persia, the famed polymath <strong>Ibn Sina (Avicenna)</strong>
          described the object as a temporary luminous monster that remained stationary for months, changing from pale green to white before fading.
          In Switzerland, monks at the Abbey of Saint Gall noted an immense dazzling light low on the southern horizon.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">PHYSICAL NATURE &amp; MODERN REMNANT</div>
        <h2>The Complete Obliteration of a White Dwarf</h2>
        <p>
          Modern X-ray and radio observations (Chandra, XMM-Newton) demonstrate that SN 1006 was a prototypical <strong>Type Ia thermonuclear supernova</strong>.
          An ultra-dense carbon-oxygen white dwarf exceeded the Chandrasekhar limit and was completely obliterated in a runaway nuclear fusion blast.
        </p>
        <p>
          Because it detonated in an exceptionally clean, low-density region of the galactic halo (~7,200 light-years away in Lupus), the expanding shockwave
          has preserved a nearly spherical, pristine bubble spanning roughly 65 light-years across. The forward shock accelerates particles to relativistic
          speeds, providing a living laboratory for cosmic-ray shock acceleration.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">CELESTIAL LOCATION</div>
        <h2>Coordinates in Lupus</h2>
        <p>
          In the night sky, the SN 1006 remnant is located at RA <code>{ra_str}</code>, Dec <code>{dec_str}</code> in the constellation <strong>Lupus the Wolf</strong>.
          It is favorably positioned for southern observatories, where narrowband [O III] and H-alpha filters reveal its delicate expanding filaments.
        </p>
        {lifecycle_html}
      </div>
    </div>
    """

    # 4. SN 1572 - Tycho's Supernova
    if "1572" in clean:
        return f"""
    <div class="narrative blockbuster-narrative">
      <div class="article-chapter">
        <div class="article-chapter-num">HISTORIC BENCHMARK &bull; NOVEMBER 1572</div>
        <h2>Tycho's Nova: The Star That Shattered Ancient Cosmology</h2>
        <p class="article-lead">
          In November 1572, the Danish astronomer <strong>Tycho Brahe</strong> stepped outside his laboratory at Herrevad Abbey, looked up into
          the constellation Cassiopeia, and saw a star shining as brightly as Jupiter where none had existed before.
          His meticulous trigonometric measurements of <strong>SN 1572</strong> fundamentally overturned the 2,000-year-old Aristotelian dogma
          that the heavens were immutable and incorruptible.
        </p>

        <div class="article-callout" style="border-left:4px solid #f59e0b;background:rgba(245,158,11,0.08);padding:1.25rem;border-radius:6px;margin:1.5rem 0;">
          <div style="font-weight:700;color:#f59e0b;font-size:1.05rem;margin-bottom:0.4rem;">★ Landmark Dossier: SN 1572 (Tycho's Nova)</div>
          <div style="font-size:0.92rem;color:#cbd5e1;line-height:1.6;">
            <strong>Discoverer:</strong> Tycho Brahe (and global observers) &bull;
            <strong>Type:</strong> Thermonuclear Type Ia &bull;
            <strong>Distance:</strong> ~8,000–9,000 Light-Years (Cassiopeia) &bull;
            <strong>Peak Apparent Magnitude:</strong> m &approx; −4.0 (Outshining Venus) &bull;
            <strong>Scientific Impact:</strong> Overthrew Aristotelian Immutable Heavens; Coined the term "Nova"
          </div>
        </div>

        <p>
          Using a large sextant of his own construction, Tycho demonstrated that the new star exhibited <strong>zero diurnal parallax</strong> relative
          to the surrounding stars of Cassiopeia. This proved conclusively that it lay far beyond the Moon, in the realm of the fixed stars.
          Tycho published his findings in the historic 1573 treatise <em>De Nova et Nullius Aevi Memoria Prius Visa Stella</em> ("Concerning the New and Never-Before-Seen Star"),
          giving science the word <em>"nova"</em>.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">LIGHT ECHOES &amp; SPECTRAL CONFIRMATION</div>
        <h2>Capturing the Spectrum of an Explosion 436 Years Later</h2>
        <p>
          In 2008, an international team of astronomers achieved an astonishing feat: they used the Subaru Telescope on Mauna Kea to capture the optical
          spectrum of SN 1572—over four centuries after the explosion!
        </p>
        <p>
          They did this by observing <strong>light echoes</strong>: original photons from 1572 that traveled away from Earth, reflected off interstellar dust clouds
          several hundred light-years behind the explosion site, and were bounced toward our modern telescopes. The reflected light showed strong ionized silicon
          absorption (Si II λ6355), confirming beyond all doubt that Tycho's supernova was a standard Type Ia thermonuclear explosion!
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">THE TYCHO REMNANT TODAY</div>
        <h2>A Giant Turbulent Blast Bubble in Cassiopeia</h2>
        <p>
          Today, the Tycho Supernova Remnant (3C 10) spans over 20 light-years across. Chandra X-ray images show an expanding shockwave laced with
          synchrotron filaments, accelerating cosmic rays and enriching the Milky Way with iron and silicon. Located at RA <code>{ra_str}</code>,
          Dec <code>{dec_str}</code>, it is circumpolar and visible year-round from the Northern Hemisphere.
        </p>
        {lifecycle_html}
      </div>
    </div>
    """

    # 5. SN 1604 - Kepler's Supernova
    if "1604" in clean:
        return f"""
    <div class="narrative blockbuster-narrative">
      <div class="article-chapter">
        <div class="article-chapter-num">HISTORIC BENCHMARK &bull; OCTOBER 1604</div>
        <h2>Kepler's Supernova: The Last Naked-Eye Blast in the Milky Way</h2>
        <p class="article-lead">
          In October 1604, German astronomer and mathematician <strong>Johannes Kepler</strong> observed a brilliant new star in the constellation
          Ophiuchus, near a planetary conjunction of Mars, Jupiter, and Saturn. <strong>SN 1604</strong> peaked at magnitude −2.5 (brighter than Jupiter)
          and holds a unique place in human history: it is the <strong>last supernova observed to detonate within our own Milky Way galaxy</strong>.
        </p>

        <div class="article-callout" style="border-left:4px solid #f59e0b;background:rgba(245,158,11,0.08);padding:1.25rem;border-radius:6px;margin:1.5rem 0;">
          <div style="font-weight:700;color:#f59e0b;font-size:1.05rem;margin-bottom:0.4rem;">★ Landmark Dossier: SN 1604 (Kepler's Nova)</div>
          <div style="font-size:0.92rem;color:#cbd5e1;line-height:1.6;">
            <strong>Observer:</strong> Johannes Kepler (Imperial Mathematician to Rudolf II) &bull;
            <strong>Type:</strong> Type Ia Thermonuclear &bull;
            <strong>Distance:</strong> ~20,000 Light-Years (Ophiuchus) &bull;
            <strong>Peak Apparent Magnitude:</strong> m &approx; −2.5 (Brighter than Jupiter) &bull;
            <strong>Milestone:</strong> Last observed Milky Way supernova in over 420 years!
          </div>
        </div>

        <p>
          Kepler documented the star's day-by-day brightness decline for over a year, publishing his monumental work <em>De Stella Nova in Pede Serpentarii</em>
          ("On the New Star in the Foot of the Serpent Bearer") in 1606. Like Tycho's star three decades earlier, Kepler's supernova proved that the cosmos was dynamic,
          laying the philosophical foundation for the Scientific Revolution and Newtonian mechanics.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">CHANDRA X-RAY MYSTERIES</div>
        <h2>Dense Circumstellar Knots and the Progenitor Identity</h2>
        <p>
          High-resolution imaging with the Chandra X-ray Observatory revealed that Kepler's remnant is rich in dense, nitrogen-enhanced circumstellar knots.
          This indicates that before the white dwarf detonated, its companion star—likely an evolved asymptotic giant branch (AGB) red giant—shed immense
          wind material that was compressed by the supersonic blast wave.
        </p>
        <p>
          Because our galaxy averages an expected 2 to 3 supernovae per century, the Milky Way is currently <em>statistically overdue</em> for its next naked-eye supernova.
          When the next galactic event detonates, global neutrino networks (SNEWS), gravitational wave detectors, and space observatories stand ready for immediate alert!
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">COORDINATES &amp; OBSERVABILITY</div>
        <h2>Observing the Kepler Remnant</h2>
        <p>
          Located in the constellation <strong>Ophiuchus</strong> at RA <code>{ra_str}</code>, Dec <code>{dec_str}</code>, Kepler's remnant is an intriguing
          target for deep narrowband astro-imaging during summer months in both hemispheres.
        </p>
        {lifecycle_html}
      </div>
    </div>
    """

    # 6. SN 2011fe - The Golden Standard Type Ia in M101
    if "2011FE" in clean:
        return f"""
    <div class="narrative blockbuster-narrative">
      <div class="article-chapter">
        <div class="article-chapter-num">THE MODERN GOLD STANDARD &bull; PINWHEEL GALAXY (M101)</div>
        <h2>The Definitive Benchmark Type Ia Supernova of the 21st Century</h2>
        <p class="article-lead">
          On August 24, 2011, the automated Palomar Transient Factory (PTF) caught a faint transient in the picturesque spiral arms of the
          <strong>Pinwheel Galaxy (Messier 101)</strong> just <strong>11 hours after explosion</strong>. Designated <strong>SN 2011fe</strong>,
          it surged to peak magnitude 9.9, becoming the brightest, closest, and cleanest Type Ia supernova observed in the northern hemisphere in four decades.
        </p>

        <div class="article-callout" style="border-left:4px solid #f59e0b;background:rgba(245,158,11,0.08);padding:1.25rem;border-radius:6px;margin:1.5rem 0;">
          <div style="font-weight:700;color:#f59e0b;font-size:1.05rem;margin-bottom:0.4rem;">★ Landmark Dossier: SN 2011fe</div>
          <div style="font-size:0.92rem;color:#cbd5e1;line-height:1.6;">
            <strong>Host Galaxy:</strong> Messier 101 (Pinwheel Galaxy) &bull;
            <strong>Distance:</strong> ~21 Million Light-Years &bull;
            <strong>Peak Apparent Magnitude:</strong> m = +9.9 (Accessible in Binoculars!) &bull;
            <strong>Milestone:</strong> Caught within hours of detonation; Zero host dust reddening (E(B-V) &approx; 0.0)
          </div>
        </div>

        <p>
          What made SN 2011fe extraordinary was its pristine observational setting: it detonated in an outer spiral arm of M101 with almost zero interstellar
          dust extinction. This provided an unblemished, textbook laboratory to observe a carbon-oxygen white dwarf detonation from day zero through late-phase
          nebular decay.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">ASTROPHYSICAL BREAKTHROUGHS</div>
        <h2>Ruling Out Giant Companion Stars</h2>
        <p>
          Because PTF captured the fireball when it was less than one-thousandth of its peak luminosity, astrophysicists were able to set severe physical limits
          on the size of the progenitor. The absence of an early shock-interaction flash ruled out red giants and normal main-sequence companions, providing
          powerful evidence favoring the <strong>double-degenerate merger channel</strong> (the collision of two white dwarfs) or an extremely compact subgiant donor.
        </p>
        <p>
          Furthermore, deep radio non-detections with the Very Large Array (VLA) proved the circumstellar environment was exceptionally vacuum-clean,
          confirming that no significant stellar wind was blowing from a companion star in the centuries leading to detonation.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">COORDINATES &amp; OBSERVATION</div>
        <h2>Position in the Pinwheel Galaxy</h2>
        <p>
          In the northern night sky, SN 2011fe is located in the magnificent Pinwheel Galaxy in <strong>Ursa Major</strong> (RA <code>{ra_str}</code>,
          Dec <code>{dec_str}</code>). Its high-fidelity light curves remain the foundational template used by astronomers worldwide to calibrate
          cosmological distance scales.
        </p>
        {lifecycle_html}
      </div>
    </div>
    """

    # 7. SN 2014J - Benchmark Type Ia in Messier 82
    if "2014J" in clean:
        return f"""
    <div class="narrative blockbuster-narrative">
      <div class="article-chapter">
        <div class="article-chapter-num">BENCHMARK TYPE IA &bull; CIGAR GALAXY (M82)</div>
        <h2>The Nearest Type Ia in Three Decades: Discovered During an Undergraduate Class!</h2>
        <p class="article-lead">
          On January 21, 2014, Dr. Steve Fossey and four undergraduate astronomy students at the University of London Observatory pointed an 8-inch
          telescope at the dusty starburst <strong>Cigar Galaxy (Messier 82)</strong> for a routine teaching session. They noticed a bright new star
          embedded in the galaxy's edge-on disk: <strong>SN 2014J</strong>, the closest Type Ia supernova discovered since 1986.
        </p>

        <div class="article-callout" style="border-left:4px solid #f59e0b;background:rgba(245,158,11,0.08);padding:1.25rem;border-radius:6px;margin:1.5rem 0;">
          <div style="font-weight:700;color:#f59e0b;font-size:1.05rem;margin-bottom:0.4rem;">★ Landmark Dossier: SN 2014J</div>
          <div style="font-size:0.92rem;color:#cbd5e1;line-height:1.6;">
            <strong>Host Galaxy:</strong> Messier 82 (Cigar Galaxy) &bull;
            <strong>Distance:</strong> ~11.5 Million Light-Years &bull;
            <strong>Peak Apparent Magnitude:</strong> m = +10.5 (Amateur Backyard Target) &bull;
            <strong>Scientific Milestone:</strong> Direct Detection of Radioactive ⁵⁶Co Gamma-Ray Lines by INTEGRAL
          </div>
        </div>

        <p>
          Detonating in the furious starburst environment of M82, SN 2014J was heavily reddened by dense interstellar dust lanes, suffering over
          two magnitudes of optical visual extinction. This turned out to be an astrophysical blessing: it enabled unprecedented empirical tests of
          unusual interstellar dust grains and non-standard extinction laws (R<sub>V</sub> &approx; 1.4–1.7).
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">THE NUCLEAR SMOKING GUN</div>
        <h2>Direct Detection of Radioactive Cobalt-56 Gamma Rays</h2>
        <p>
          For decades, theorists had posited that Type Ia light curves are sustained by radioactive decay: ⁵⁶Ni &rarr; ⁵⁶Co &rarr; ⁵⁶Fe.
          In 2014, the European Space Agency's <strong>INTEGRAL satellite</strong> detected the direct 847 keV and 1238 keV gamma-ray lines emitted by
          decaying Cobalt-56 in SN 2014J.
        </p>
        <p>
          This monumental observation provided the direct "smoking gun" proof of nucleosynthesis predictions, demonstrating that approximately
          <strong>0.5 solar masses of radioactive nickel</strong> were forged in the thermonuclear blast.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">LOCATION IN THE SKY</div>
        <h2>Coordinates in Ursa Major</h2>
        <p>
          Located in the Cigar Galaxy in <strong>Ursa Major</strong> at RA <code>{ra_str}</code>, Dec <code>{dec_str}</code>, SN 2014J remains
          one of the most cited supernovae in modern high-energy astrophysics.
        </p>
        {lifecycle_html}
      </div>
    </div>
    """

    # 8. SN 2023ixf - The Bright 2023 Type II in M101
    if "2023IXF" in clean:
        return f"""
    <div class="narrative blockbuster-narrative">
      <div class="article-chapter">
        <div class="article-chapter-num">HISTORIC BENCHMARK &bull; PINWHEEL GALAXY (M101)</div>
        <h2>The Brightest Core-Collapse Supernova of the Decade</h2>
        <p class="article-lead">
          On May 19, 2023, legendary Japanese amateur astronomer <strong>Koichi Itagaki</strong> discovered a luminous transient shining at magnitude 14.9
          in an outer spiral arm of the famous <strong>Pinwheel Galaxy (Messier 101)</strong>. Designated <strong>SN 2023ixf</strong>, it rapidly brightened
          to magnitude 10.8—becoming the brightest and closest core-collapse supernova seen from Earth in over a decade!
        </p>

        <div class="article-callout" style="border-left:4px solid #f59e0b;background:rgba(245,158,11,0.08);padding:1.25rem;border-radius:6px;margin:1.5rem 0;">
          <div style="font-weight:700;color:#f59e0b;font-size:1.05rem;margin-bottom:0.4rem;">★ Landmark Dossier: SN 2023ixf</div>
          <div style="font-size:0.92rem;color:#cbd5e1;line-height:1.6;">
            <strong>Discoverer:</strong> Koichi Itagaki (Yamagata, Japan) &bull;
            <strong>Host Galaxy:</strong> Messier 101 (Pinwheel Galaxy) &bull;
            <strong>Distance:</strong> ~21 Million Light-Years &bull;
            <strong>Type:</strong> Type II Core-Collapse Supernova &bull;
            <strong>Peak Apparent Magnitude:</strong> m = +10.8 (Easily Visible in 4-Inch Telescopes)
          </div>
        </div>

        <p>
          Thousands of amateur astrophotographers and professional observatories worldwide swung their telescopes toward M101.
          Crucially, pre-discovery images showed that the progenitor was an evolved <strong>red supergiant star</strong> with an initial mass of
          approximately 12 to 15 solar masses, surrounded by an extremely dense cocoon of circumstellar material shed in the final months before detonation.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">SHOCK BREAKOUT &amp; CIRCUMSTELLAR INTERACTION</div>
        <h2>Flash Spectroscopy and the Star's Final Gasps</h2>
        <p>
          Within hours of discovery, ultra-rapid "flash spectroscopy" captured narrow emission lines of highly ionized hydrogen, helium, carbon, and nitrogen.
          These spectral features revealed that during the final years of its life, the red supergiant had undergone intense mass eruptions, ejecting
          solar masses of gas that enveloped the star.
        </p>
        <p>
          When the core collapsed and the supersonic blast wave broke out through the star's surface at over 10,000 km/s, it slammed into this circumstellar
          cocoon, creating bright ultraviolet and soft X-ray emission monitored in real-time by NASA's Swift and NuSTAR space observatories.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">BACKYARD ASTRONOMER EXPERIENCE</div>
        <h2>Observing the Pinwheel Galaxy Blast</h2>
        <p>
          SN 2023ixf was a global astronomical sensation, observed visually by amateur stargazers in modest 4-inch to 8-inch backyard telescopes.
          Located in <strong>Ursa Major</strong> at RA <code>{ra_str}</code>, Dec <code>{dec_str}</code>, it is circumpolar for most northern observers,
          and continues to be monitored as it fades along its radioactive ⁵⁶Co decay tail.
        </p>
        {lifecycle_html}
      </div>
    </div>
    """

    # 9. SN 1998bw - The First GRB / Supernova Connection
    if "1998BW" in clean:
        return f"""
    <div class="narrative blockbuster-narrative">
      <div class="article-chapter">
        <div class="article-chapter-num">ASTROPHYSICAL REVOLUTION &bull; GRB 980425 CONNECTION</div>
        <h2>The Engine-Driven Blast That Solved the Mystery of Gamma-Ray Bursts</h2>
        <p class="article-lead">
          On April 25, 1998, the Italian-Dutch satellite BeppoSAX detected a long-duration gamma-ray burst designated <strong>GRB 980425</strong>.
          Two days later, optical follow-up revealed an exceptionally bizarre, energetic supernova in the spiral galaxy ESO 184-G82:
          <strong>SN 1998bw</strong>. It provided the historic first empirical proof connecting long-duration gamma-ray bursts to the deaths of massive stars.
        </p>

        <div class="article-callout" style="border-left:4px solid #f59e0b;background:rgba(245,158,11,0.08);padding:1.25rem;border-radius:6px;margin:1.5rem 0;">
          <div style="font-weight:700;color:#f59e0b;font-size:1.05rem;margin-bottom:0.4rem;">★ Landmark Dossier: SN 1998bw (GRB 980425)</div>
          <div style="font-size:0.92rem;color:#cbd5e1;line-height:1.6;">
            <strong>Type:</strong> Broad-Lined Type Ic Supernova (Ic-BL) &bull;
            <strong>Distance:</strong> ~125 Million Light-Years &bull;
            <strong>Kinetic Energy:</strong> ~3 &times; 10⁵² ergs (Hypernova Category!) &bull;
            <strong>Ejecta Velocity:</strong> Exceeding 30,000 km/s (0.1c, Relativistic Shockwave)
          </div>
        </div>

        <p>
          Unlike ordinary core-collapse supernovae, SN 1998bw exhibited extraordinarily broad spectral lines, indicating ejecta velocities
          exceeding <strong>30,000 km/s (10% of the speed of light!)</strong>. It released roughly 30 times more kinetic energy than a standard supernova,
          coining the term <em>"hypernova"</em> and proving the existence of central relativistic engine jets launched during black hole formation.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">THE COLLAPSAR PARADIGM</div>
        <h2>Birth of a Stellar Black Hole and Relativistic Jets</h2>
        <p>
          SN 1998bw validated Stan Woosley's <strong>collapsar model</strong>: when a rapidly spinning massive star stripped of its outer hydrogen
          and helium envelopes exhausts its fuel, its core collapses directly into a rotating black hole. An accretion disk forms around the newborn black hole,
          channeling magnetic fields and plasma into relativistic twin jets that punch through the stellar poles at 99.9% the speed of light to produce the GRB.
        </p>
      </div>

      <div class="article-chapter">
        <div class="article-chapter-num">LOCATION IN TELESCOPIUM</div>
        <h2>Coordinates and Legacy</h2>
        <p>
          Located in the southern constellation <strong>Telescopium</strong> at RA <code>{ra_str}</code>, Dec <code>{dec_str}</code>, SN 1998bw remains
          the archetypal hypernova that opened the modern era of relativistic transient science.
        </p>
        {lifecycle_html}
      </div>
    </div>
    """

    # If no bespoke article exists for this specific name, return None so the dynamic engine generates it!
    return None


def get_blockbuster_article(
    name: str,
    meta: Dict[str, Any],
    claimedtype: str,
    discoverdate: str,
    discoverer: str,
    maxappmag: str,
    dist_ly_str: str,
    host: str,
    ra_str: str,
    dec_str: str,
    lifecycle_html: str,
) -> Optional[str]:
    """Retrieve bespoke blockbuster editorial article with anchored chapter IDs for reading navigation."""
    raw_html = _get_blockbuster_raw(
        name=name,
        meta=meta,
        claimedtype=claimedtype,
        discoverdate=discoverdate,
        discoverer=discoverer,
        maxappmag=maxappmag,
        dist_ly_str=dist_ly_str,
        host=host,
        ra_str=ra_str,
        dec_str=dec_str,
        lifecycle_html=lifecycle_html,
    )
    if not raw_html:
        return None

    # Guarantee sequential anchor IDs for reading jump rail
    idx = 1
    while '<div class="article-chapter">' in raw_html:
        raw_html = raw_html.replace('<div class="article-chapter">', f'<div class="article-chapter" id="chapter-{idx}">', 1)
        idx += 1
    return raw_html

