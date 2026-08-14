await harness.goToScene('PVZ Battle');

const placePlantAt = async (plantType, screenX, screenY) => {
  harness.setSceneVariable('PlantingMode', true);
  harness.setSceneVariable('HasPlacementTarget', true);
  harness.setSceneVariable('SelectedPlantType', plantType);
  harness.setMousePositionScreen(screenX, screenY);
  harness.setMouseButtonPressed(true, 'left');
  await harness.stepFrames(1);
  harness.setMouseButtonPressed(false, 'left');
  await harness.stepFrames(1);
};

await placePlantAt('Sunflower', 300, 330);

harness.assert(
  harness.getObjects('SunflowerPlant').length === 1,
  'A sunflower must be created on the selected lawn tile.'
);
harness.assert(
  harness.getSceneVariable('SunAmount')?.value === 450,
  `Sunflower placement must deduct 50 sun; balance was ${
    harness.getSceneVariable('SunAmount')?.value
  }.`
);

await placePlantAt('Peashooter', 500, 330);

harness.assert(
  harness.getObjects('PeashooterPlant').length === 1,
  'A peashooter must be created on the selected lawn tile.'
);
harness.assert(
  harness.getSceneVariable('SunAmount')?.value === 350,
  `Peashooter placement must deduct 100 sun; balance was ${
    harness.getSceneVariable('SunAmount')?.value
  }.`
);

harness.watch('SunflowerPlant');
harness.watch('PeashooterPlant');
