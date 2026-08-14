await harness.goToScene('PVZ Battle', { skipCreatingInstances: true });

const zombie = harness.spawn('Zombie', 900, 350, 5);
const highPea = harness.spawn('PeaProjectile', 900, 350, 500);

await harness.stepFrames(1);

const highPeaSurvived = harness
  .getObjects('PeaProjectile')
  .some(projectile => projectile.id === highPea.id);
const hpAfterSeparatedZ = harness.getObjectVariable(zombie.id, 'HP')?.value;

harness.assert(
  highPeaSurvived,
  'A pea at the same X/Y but a separated Z must not collide with the zombie.'
);
harness.assert(
  hpAfterSeparatedZ === 100,
  `The separated-Z pea must not damage the zombie; HP was ${hpAfterSeparatedZ}.`
);

harness.removeObject(highPea.id);

const currentZombie = harness
  .getObjects('Zombie')
  .find(instance => instance.id === zombie.id);
harness.assert(Boolean(currentZombie), 'The test zombie must still exist.');

const collidingPea = harness.spawn(
  'PeaProjectile',
  currentZombie?.x ?? 900,
  currentZombie?.y ?? 350,
  52
);

await harness.stepFrames(1);

const collidingPeaSurvived = harness
  .getObjects('PeaProjectile')
  .some(projectile => projectile.id === collidingPea.id);
harness.assert(
  !collidingPeaSurvived,
  'A pea whose XYZ volume overlaps the zombie must be consumed by the hit.'
);

const damageDelivered = await harness.stepUntil(
  () => harness.getObjectVariable(zombie.id, 'HP')?.value === 80,
  { maxFrames: 4 }
);
harness.assert(
  damageDelivered,
  `The overlapping pea must reduce zombie HP from 100 to 80; HP was ${
    harness.getObjectVariable(zombie.id, 'HP')?.value
  }.`
);

harness.watch('Zombie');
harness.watch('PeaProjectile');
